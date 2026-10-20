// Production function bodies are inserted by run_ws_audio_send_host_test.py.
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cerrno>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
#include <arpa/inet.h>

// @CONSTANTS
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define ESP_OK 0
#define pdPASS 1
#define portMAX_DELAY 0xffffffffu
#define portTICK_PERIOD_MS 1
#define MAX_WEBSOCKET_HEADER_SIZE 16
#define WS_SIZE16 126
#define WS_SIZE64 127
#define WS_TRANSPORT_OPCODES_FIN 0x80
#define WS_TRANSPORT_OPCODES_BINARY 2
#define WS_TRANSPORT_OPCODES_TEXT 1
#define WEBSOCKET_ERROR_TYPE_TCP_TRANSPORT 1
using TickType_t = uint32_t;
using ws_transport_opcodes_t = int;

struct Parent {
    std::deque<int> polls, writes;
    int poll_calls = 0, write_calls = 0;
};
struct transport_ws_t { Parent* parent; };
using esp_transport_handle_t = transport_ws_t*;
static transport_ws_t* esp_transport_get_context_data(esp_transport_handle_t t) { return t; }
static int esp_transport_poll_write(Parent* p, int) {
    ++p->poll_calls;
    if (p->polls.empty()) return 1;
    int value = p->polls.front(); p->polls.pop_front(); return value;
}
static int esp_transport_write(Parent* p, const char*, int len, int) {
    ++p->write_calls;
    if (p->writes.empty()) return len;
    int value = p->writes.front(); p->writes.pop_front(); return value;
}
static void esp_fill_random(void* data, size_t len) { memset(data, 0x55, len); }
// @TRANSPORT
static int esp_transport_ws_send_raw(esp_transport_handle_t t, int op, char* data, int len, int timeout) {
    return _ws_write(t, op, 0x80, data, len, timeout);
}

struct Lock { int depth = 0; bool fail_next = false; };
static int xSemaphoreTakeRecursive(Lock* lock, uint32_t) {
    if (lock->fail_next) { lock->fail_next = false; return 0; }
    ++lock->depth; return pdPASS;
}
static void xSemaphoreGiveRecursive(Lock* lock) { assert(lock->depth > 0); --lock->depth; }
struct Client {
    esp_transport_handle_t transport;
    Lock storage_lock, storage_tx;
    Lock* lock = &storage_lock;
    Lock* tx_lock = &storage_tx;
    bool connected = true;
    int buffer_size = 1024, aborts = 0, errors = 0, buffers = 0;
    char tx_buffer[1024];
};
using esp_websocket_client_handle_t = Client*;
struct TlsError { int last_error, esp_tls_error_code, esp_tls_flags; };
using esp_tls_error_handle_t = TlsError*;
static esp_tls_error_handle_t esp_transport_get_error_handle(esp_transport_handle_t) { return nullptr; }
static const char* esp_err_to_name(int) { return "fake"; }
static bool esp_websocket_client_is_connected(Client* c) { return c->connected; }
static int esp_websocket_new_buf(Client* c, bool) { ++c->buffers; return ESP_OK; }
static void esp_websocket_free_buf(Client* c, bool) { assert(c->buffers > 0); --c->buffers; }
static void esp_websocket_client_error(Client* c, const char*, ...) { ++c->errors; }
static void esp_websocket_client_abort_connection(Client* c, int) { ++c->aborts; c->connected = false; }
// @CLIENT

static int64_t now_us = 3000000;
static int64_t esp_timer_get_time() { return now_us; }
struct Socket {
    Client* client;
    bool connected_ = true, last_send_transient_ = false;
    int last_error_ = 0, last_sock_errno_ = 0;
    int64_t last_tx_ok_us_ = 0;
    int64_t transient_fail_since_us_ = 0;
    const char* last_send_transient_class_ = "";
    // @FINALIZE
    bool Send(const void* data, size_t len, bool) {
        const int sent = esp_websocket_client_send_with_exact_opcode(
            client, WS_TRANSPORT_OPCODES_BINARY | WS_TRANSPORT_OPCODES_FIN,
            static_cast<const uint8_t*>(data), len, 500);
        connected_ = client->connected;
        return FinalizeSend(sent, len, errno);
    }
    bool IsConnected() const { return client->connected; }
    bool WasLastSendTransient() const { return last_send_transient_; }
    const char* LastSendTransientClass() const { return last_send_transient_class_; }
};
struct AudioStreamPacket {
    uint32_t timestamp = 0, upload_generation = 1;
    int64_t upload_created_us = 0;
    std::vector<uint8_t> payload;
};
struct BinaryProtocol2 {
    uint16_t version, type;
    uint32_t reserved, timestamp, payload_size;
    uint8_t payload[0];
} __attribute__((packed));
struct BinaryProtocol3 { uint8_t type, reserved; uint16_t payload_size; uint8_t payload[0]; } __attribute__((packed));
struct WebsocketProtocol {
    Socket* websocket_;
    std::mutex ws_mutex_;
    int version_ = 1, fatal_calls = 0;
    uint32_t consecutive_transient_failures_ = 0;
    bool SendAudio(std::unique_ptr<AudioStreamPacket> packet);
    void HandleAudioSendFailure() { ++fatal_calls; websocket_ = nullptr; }
};
// @PROTOCOL
struct AudioService {
    std::mutex audio_queue_mutex_;
    std::condition_variable audio_queue_cv_;
    std::deque<std::unique_ptr<AudioStreamPacket>> audio_send_queue_;
    std::atomic<uint32_t> upload_generation_{1}, upload_stale_drop_{0};
    std::unique_ptr<AudioStreamPacket> PopPacketFromSendQueue();
};
// @QUEUE

static std::unique_ptr<AudioStreamPacket> packet(int size = 130) {
    auto p = std::make_unique<AudioStreamPacket>(); p->payload.resize(size, 0x25); return p;
}
static void locks_released(Client& c) {
    assert(c.storage_lock.depth == 0 && c.storage_tx.depth == 0 && c.buffers == 0);
}
static int send(Client& c, int len = 130, int op = 0x82) {
    std::vector<uint8_t> data(len, 0x25);
    int result = esp_websocket_client_send_with_exact_opcode(&c, op, data.data(), len, 500);
    locks_released(c);
    return result;
}
int main() {
    // The reported failure: 130 bytes, pre-write poll timeout, stale errno=2.
    // Exercise the REAL protocol, wrapper, client, and transport together.
    for (int version : {1, 2, 3}) {
        Parent parent; transport_ws_t t{&parent}; Client c{&t}; Socket socket{&c};
        WebsocketProtocol protocol{&socket}; protocol.version_ = version;
        for (int i = 0; i < 25; ++i) {
            parent.polls.push_back(0); errno = 2;
            assert(!protocol.SendAudio(packet()));
            assert(c.connected && c.aborts == 0 && c.errors == 0 && protocol.fatal_calls == 0);
            assert(protocol.consecutive_transient_failures_ == unsigned(i + 1));
            assert(parent.write_calls == 0);
            locks_released(c);
        }
        assert(protocol.SendAudio(packet()));
        assert(protocol.consecutive_transient_failures_ == 0 && c.connected);
        locks_released(c);
        // TX lock timeout must not use stale errno to classify the message,
        // and must be distinguishable from socket_not_writable (-2).
#ifdef CONFIG_ESP_WS_CLIENT_SEPARATE_TX_LOCK
        c.storage_tx.fail_next = true;
#else
        c.storage_lock.fail_next = true;
#endif
        errno = 2;
        assert(!protocol.SendAudio(packet()));
        assert(c.connected && protocol.fatal_calls == 0);
        assert(socket.WasLastSendTransient());
        assert(std::string(socket.LastSendTransientClass()) == "tx_lock_timeout");
        assert(protocol.SendAudio(packet()));
        locks_released(c);
        // Pre-write poll timeout remains -2 / socket_not_writable.
        parent.polls.push_back(0); errno = 2;
        assert(!protocol.SendAudio(packet()));
        assert(std::string(socket.LastSendTransientClass()) == "socket_not_writable");
        assert(protocol.SendAudio(packet()));
        locks_released(c);
    }
    // Zero, negative, short, and sentinel-like payload writes AFTER the header
    // must abort, even with EAGAIN/ETIMEDOUT and a previously healthy socket.
    for (int payload_return : {0, -1, -2, 60}) {
        Parent parent; parent.writes = {8, payload_return};
        transport_ws_t t{&parent}; Client c{&t}; Socket socket{&c}; WebsocketProtocol protocol{&socket};
        errno = EAGAIN;
        assert(!protocol.SendAudio(packet()));
        assert(!c.connected && c.aborts == 1 && protocol.fatal_calls == 1);
        assert(parent.write_calls == 2); locks_released(c);
    }
    for (int header_return : {0, 3, -1}) {
        Parent parent; parent.writes = {header_return}; transport_ws_t t{&parent}; Client c{&t};
        assert(send(c) == -1 && c.aborts == 1 && parent.write_calls == 1);
    }
    {
        Parent parent; parent.polls = {-1}; transport_ws_t t{&parent}; Client c{&t};
        assert(send(c) == -1 && c.aborts == 1 && parent.write_calls == 0);
    }
    // A timeout after the first fragment cannot discard the unfinished message.
    {
        Parent parent; parent.polls = {1, 0}; transport_ws_t t{&parent}; Client c{&t}; c.buffer_size = 64;
        assert(send(c) == -1 && c.aborts == 1 && parent.write_calls == 2);
    }
    // A timeout before the FIRST fragment of a complete message is safe.
    {
        Parent parent; parent.polls = {0}; transport_ws_t t{&parent}; Client c{&t}; c.buffer_size = 64;
        assert(send(c) == ESP_WEBSOCKET_CLIENT_SEND_NOT_STARTED && c.aborts == 0);
        assert(send(c) == 130 && c.connected);
    }
    // TX lock timeout uses a distinct not-started code.
    {
        Parent parent; transport_ws_t t{&parent}; Client c{&t};
#ifdef CONFIG_ESP_WS_CLIENT_SEPARATE_TX_LOCK
        c.storage_tx.fail_next = true;
#else
        c.storage_lock.fail_next = true;
#endif
        assert(send(c) == ESP_WEBSOCKET_CLIENT_SEND_TX_LOCK_TIMEOUT && c.aborts == 0);
        assert(send(c) == 130 && c.connected);
    }
    for (int opcode : {0x00, 0x02, 0x80}) {
        Parent parent; parent.polls = {0}; transport_ws_t t{&parent}; Client c{&t};
        assert(send(c, 130, opcode) == -1 && c.aborts == 1);
    }
    for (int opcode : {0x81, 0x82}) {
        Parent parent; parent.polls = {0}; transport_ws_t t{&parent}; Client c{&t};
        assert(send(c, 0, opcode) == ESP_WEBSOCKET_CLIENT_SEND_NOT_STARTED && c.connected);
        assert(send(c, 0, opcode) == 0 && c.connected);
    }
    // Already disconnected/null protocol sockets fail quietly.
    {
        Parent parent; transport_ws_t t{&parent}; Client c{&t}; c.connected = false;
        Socket socket{&c}; WebsocketProtocol protocol{&socket};
        assert(!protocol.SendAudio(packet()) && protocol.fatal_calls == 0);
        protocol.websocket_ = nullptr;
        assert(!protocol.SendAudio(packet()) && protocol.fatal_calls == 0);
    }
    // Real queue function: drop old generations and old captured speech, retain
    // the boundary age and wake packets without a timestamp.
    {
        AudioService audio;
        auto wrong_generation = packet(); wrong_generation->upload_generation = 0;
        auto old = packet(); old->upload_created_us = now_us - 1500001;
        auto boundary = packet(); boundary->upload_created_us = now_us - 1500000;
        auto fresh = packet(); fresh->upload_created_us = now_us - 100;
        audio.audio_send_queue_.push_back(std::move(wrong_generation));
        audio.audio_send_queue_.push_back(std::move(old));
        audio.audio_send_queue_.push_back(std::move(boundary));
        audio.audio_send_queue_.push_back(std::move(fresh));
        audio.audio_send_queue_.push_back(packet());
        assert(audio.PopPacketFromSendQueue()->upload_created_us == now_us - 1500000);
        assert(audio.upload_stale_drop_ == 2);
        assert(audio.PopPacketFromSendQueue()->upload_created_us == now_us - 100);
        assert(audio.PopPacketFromSendQueue()->upload_created_us == 0);
        assert(audio.PopPacketFromSendQueue() == nullptr);
    }
    return 0;
}
