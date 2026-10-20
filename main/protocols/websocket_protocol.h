#ifndef _WEBSOCKET_PROTOCOL_H_
#define _WEBSOCKET_PROTOCOL_H_


#include "protocol.h"
#include "auth_connection.h"

#include <web_socket.h>
#include "websocket_connection_gate.h"
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/event_groups.h>
#include <functional>
#include <mutex>
#include <string>

#define WEBSOCKET_PROTOCOL_SERVER_HELLO_EVENT (1 << 0)

class WebsocketProtocol : public Protocol {
public:
    WebsocketProtocol();
    ~WebsocketProtocol();

    bool Start() override;
    bool SendAudio(std::unique_ptr<AudioStreamPacket> packet) override;
    bool OpenAudioChannel() override;
    bool NeedsCredentialRefresh() const override;
    void AcceptRefreshedCredentials() override;
    void CloseAudioChannel() override;
    bool IsAudioChannelOpened() const override;


private:
    EventGroupHandle_t event_group_handle_;
    std::unique_ptr<WebSocket> websocket_;
    // Serializes every access to websocket_ (send / null-check / close / reset).
    // The OTA worker sends control status from its own task and must never race
    // the main-loop audio send or a CloseAudioChannel() reset of the same socket.
    mutable std::mutex ws_mutex_;
    int version_ = 1;
    // Set only after an authenticated server error explicitly says that this
    // device is no longer allowed to use its current WSS credential. It stops
    // local retry loops until the device is restarted and bootstrapped again.
    std::atomic<bool> terminal_auth_rejected_{false};
    // Diagnostic only; recoverable audio timeouts never tear down the link.
    uint32_t consecutive_transient_failures_ = 0;
    // Vision credential generation for the socket currently being opened /
    // owned. Captured into disconnect callbacks so a stale close cannot clear
    // a newer connection's credentials.
    uint32_t connection_generation_ = 0;
    uint32_t opened_credential_epoch_ = 0;
    // Mutex-backed admission gate: Begin/End and RX (including hello) share
    // this lock so stale sockets cannot race a newer connection.
    WebsocketConnectionGate connection_gate_;

    void ParseServerHello(const cJSON* root, uint32_t source_generation);
    bool HandleTerminalAuthError(const cJSON* root);
    bool SendText(const std::string& text) override;
    std::string GetHelloMessage();

    // Fatal audio-send failure path: release the current socket, then publish
    // the network error exactly once. Transient timeouts do not call this.
    void HandleAudioSendFailure();
};

#endif
