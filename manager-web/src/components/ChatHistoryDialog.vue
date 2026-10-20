<template>
  <el-dialog :visible.sync="dialogVisible" width="1000px" append-to-body :before-close="handleClose" custom-class="xn-chat-dialog">
    <div slot="title" class="ch-title">
      <span class="ch-title__text">{{ $t('xn.agents.chat.title', { name: agentName }) }}</span>
      <span v-if="currentMacAddress" class="xn-tag xn-tag--muted xn-num">{{ currentMacAddress }}</span>
      <demo-tag />
    </div>

    <div class="ch">
      <!-- 左：会话列表（滚动到底加载更多） -->
      <aside class="ch-sessions" v-loading="loading && !sessions.length" @scroll="handleScroll">
        <xn-empty v-if="sessionsFailed && !sessions.length" error @retry="retrySessions" />
        <template v-else>
          <button v-for="session in sessions" :key="session.sessionId" type="button" class="ch-session"
            :class="{ 'is-on': currentSessionId === session.sessionId }" :aria-current="currentSessionId === session.sessionId ? 'true' : null"
            @click="selectSession(session)">
            <span class="ch-ava ch-ava--user" :class="'tone-' + getUserAvatar(session.sessionId)" aria-hidden="true"><xn-icon name="chat" /></span>
            <span class="ch-session__time xn-num">{{ formatTime(session.createdAt) }}</span>
            <span class="ch-session__count xn-num" :title="$t('xn.agents.chat.count', { n: session.chatCount })">{{ session.chatCount > 99 ? '99+' : session.chatCount }}</span>
          </button>
          <p v-if="loading && sessions.length" class="ch-more">{{ $t('chatHistory.loading') }}</p>
          <p v-else-if="sessions.length && !hasMore" class="ch-more">{{ $t('chatHistory.noMoreRecords') }}</p>
          <p v-else-if="sessions.length && hasMore" class="ch-more">
            <el-button type="text" @click="loadSessions">{{ $t('xn.agents.chat.loadMore') }}</el-button>
          </p>
        </template>
      </aside>

      <!-- 右：消息 -->
      <section class="ch-content" v-loading="messagesLoading">
        <xn-empty v-if="!sessionsFailed && !loading && !isFirstLoad && !sessions.length" icon="chat"
          :title="$t('xn.agents.chat.emptyTitle')" :description="$t('xn.agents.chat.emptyDesc')" />
        <xn-empty v-else-if="messagesFailed" error @retry="selectSession({ sessionId: currentSessionId })" />
        <div v-else-if="currentSessionId" class="ch-messages">
          <template v-for="message in messagesWithTime">
            <div v-if="message.type === 'time'" :key="message.id" class="ch-time xn-num">{{ message.content }}</div>
            <div v-else :key="message.id" class="ch-msg" :class="{ 'ch-msg--user': message.chatType === 1 }">
              <span v-if="message.chatType === 1" class="ch-ava ch-ava--user" :class="'tone-' + getUserAvatar(currentSessionId)" aria-hidden="true"><xn-icon name="agent" /></span>
              <span v-else class="ch-ava ch-ava--agent" aria-hidden="true">{{ agentInitial }}</span>
              <div class="ch-bubble">
                <span class="ch-bubble__text">{{ extractContentFromString(message.content) }}</span>
                <button v-if="message.audioId" type="button" class="ch-play" :class="{ 'is-playing': playingAudioId === message.audioId }"
                  :aria-label="playingAudioId === message.audioId ? $t('xn.agents.chat.stop') : $t('xn.agents.chat.play')"
                  :title="playingAudioId === message.audioId ? $t('xn.agents.chat.stop') : $t('xn.agents.chat.play')"
                  @click="playAudio(message)"><i :class="getAudioIconClass(message)"></i></button>
              </div>
            </div>
          </template>
        </div>
        <p v-else-if="sessions.length" class="ch-pick">{{ $t('chatHistory.selectSession') }}</p>
      </section>
    </div>

    <div slot="footer" class="ch-foot">
      <span v-if="isMock" class="xn-muted ch-foot__note">{{ $t('xn.agents.chat.downloadNote') }}</span>
      <el-button :disabled="!currentSessionId" @click="downloadCurrentSessionWithPrevious"><xn-icon name="download" /> {{ $t('chatHistory.downloadCurrentWithPreviousSessions') }}</el-button>
      <el-button type="primary" :disabled="!currentSessionId" @click="downloadCurrentSession"><xn-icon name="download" /> {{ $t('chatHistory.downloadCurrentSession') }}</el-button>
    </div>
  </el-dialog>
</template>

<script>
import Api from '@/apis/api';
import { playableUrl, openDownload, IS_MOCK } from '@/utils/media';

const LOAD_TIMEOUT = 10000;   // 回调迟迟不来（例如接口返回业务错误时不会进入 success 回调）时显示失败状态

export default {
    name: 'ChatHistoryDialog',
    props: {
        visible: {
            type: Boolean,
            default: false
        },
        agentId: {
            type: String,
            required: true
        },
        agentName: {
            type: String,
            required: true
        }
    },
    data() {
        return {
            dialogVisible: false,
            sessions: [],
            messages: [],
            currentSessionId: '',
            currentMacAddress: '',
            page: 1,
            limit: 20,
            loading: false,
            hasMore: true,
            scrollTimer: null,
            isFirstLoad: true,
            playingAudioId: null,
            audioElement: null,
            sessionsFailed: false,
            messagesLoading: false,
            messagesFailed: false,
            sessionsWatch: null,
            messagesWatch: null,
            isMock: IS_MOCK,
        };
    },
    watch: {
        visible(val) {
            this.dialogVisible = val;
            if (val) {
                this.resetData();
                this.loadSessions();
            }
        },
        dialogVisible(val) {
            if (!val) {
                this.stopAudio();
                this.$emit('update:visible', false);
            }
        }
    },
    computed: {
        agentInitial() {
            return Array.from(this.agentName || '?')[0];
        },
        messagesWithTime() {
            if (!this.messages || this.messages.length === 0) return [];

            const result = [];
            const TIME_INTERVAL = 60 * 1000; // 1分钟的时间间隔（毫秒）

            // 添加第一条消息的时间标记
            if (this.messages[0]) {
                result.push({
                    type: 'time',
                    content: this.formatTime(this.messages[0].createdAt),
                    id: `time-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
                });
            }

            // 处理消息列表
            for (let i = 0; i < this.messages.length; i++) {
                const currentMessage = this.messages[i];
                result.push(currentMessage.id ? currentMessage : { ...currentMessage, id: `m-${i}` });

                // 检查是否需要添加时间标记
                if (i < this.messages.length - 1) {
                    const currentTime = new Date(currentMessage.createdAt).getTime();
                    const nextTime = new Date(this.messages[i + 1].createdAt).getTime();

                    if (nextTime - currentTime > TIME_INTERVAL) {
                        result.push({
                            type: 'time',
                            content: this.formatTime(this.messages[i + 1].createdAt),
                            id: `time-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
                        });
                    }
                }
            }

            return result;
        }
    },
    beforeDestroy() {
        this.stopAudio();
        clearTimeout(this.sessionsWatch);
        clearTimeout(this.messagesWatch);
    },
    methods: {
        /**
         * 从 content 字段中提取聊天内容
         * 如果 content 是 JSON 格式（如 {"speaker": "未知说话人", "content": "现在几点了。"}），则提取 content 字段
         * 如果 content 是普通字符串，则直接返回
         */
        extractContentFromString(content) {
            if (!content || content.trim() === '') {
                return content;
            }
            try {
                const jsonObj = JSON.parse(content);
                if (jsonObj && typeof jsonObj === 'object' && jsonObj.content) {
                    return jsonObj.content;
                }
            } catch (e) {
                // 如果不是有效的 JSON，直接返回原内容
            }
            return content;
        },
        resetData() {
            this.sessions = [];
            this.messages = [];
            this.currentSessionId = '';
            this.currentMacAddress = '';
            this.page = 1;
            this.loading = false;
            this.hasMore = true;
            this.isFirstLoad = true;
            this.sessionsFailed = false;
            this.messagesFailed = false;
            this.messagesLoading = false;
        },
        handleClose() {
            this.dialogVisible = false;
        },
        retrySessions() {
            this.resetData();
            this.loadSessions();
        },
        loadSessions() {
            if (this.loading || (!this.isFirstLoad && !this.hasMore)) {
                return;
            }

            this.loading = true;
            this.sessionsFailed = false;
            const params = {
                page: this.page,
                limit: this.limit
            };
            const agentId = this.agentId;
            clearTimeout(this.sessionsWatch);
            this.sessionsWatch = setTimeout(() => {
                this.loading = false;
                this.sessionsFailed = true;
                this.isFirstLoad = false;
            }, LOAD_TIMEOUT);

            Api.agent.getAgentSessions(agentId, params, (res) => {
                if (agentId !== this.agentId) return;
                clearTimeout(this.sessionsWatch);
                if (res.data && res.data.data && Array.isArray(res.data.data.list)) {
                    const list = res.data.data.list;
                    this.hasMore = list.length === this.limit;

                    this.sessions = [...this.sessions, ...list];
                    this.page++;

                    if (this.sessions.length > 0 && !this.currentSessionId) {
                        this.selectSession(this.sessions[0]);
                    }
                } else {
                    this.sessionsFailed = true;
                }
                this.loading = false;
                this.isFirstLoad = false;
            });
        },
        selectSession(session) {
            if (!session || !session.sessionId) return;
            this.stopAudio();
            this.currentSessionId = session.sessionId;
            this.messagesLoading = true;
            this.messagesFailed = false;
            clearTimeout(this.messagesWatch);
            this.messagesWatch = setTimeout(() => {
                this.messagesLoading = false;
                this.messagesFailed = true;
            }, LOAD_TIMEOUT);
            Api.agent.getAgentChatHistory(this.agentId, session.sessionId, (res) => {
                if (session.sessionId !== this.currentSessionId) return;
                clearTimeout(this.messagesWatch);
                this.messagesLoading = false;
                if (res.data && res.data.data) {
                    this.messages = res.data.data;
                    if (this.messages.length > 0 && this.messages[0].macAddress) {
                        this.currentMacAddress = this.messages[0].macAddress;
                    }
                    this.$nextTick(() => {
                        const box = this.$el && this.$el.querySelector && this.$el.querySelector('.ch-content');
                        if (box) box.scrollTop = 0;
                    });
                } else {
                    this.messagesFailed = true;
                }
            });
        },
        handleScroll(e) {
            if (this.scrollTimer) {
                clearTimeout(this.scrollTimer);
            }
            const target = e.target;
            this.scrollTimer = setTimeout(() => {
                const { scrollTop, scrollHeight, clientHeight } = target;
                // 当滚动到底部时加载更多
                if (scrollHeight - scrollTop <= clientHeight + 50) {
                    this.loadSessions();
                }
            }, 200);
        },
        formatTime(timestamp) {
            const date = new Date(timestamp);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const yesterday = new Date(today);
            yesterday.setDate(yesterday.getDate() - 1);

            const hours = date.getHours().toString().padStart(2, '0');
            const minutes = date.getMinutes().toString().padStart(2, '0');

            if (date >= today) {
                return `${this.$t('chatHistory.today')} ${hours}:${minutes}`;
            } else if (date >= yesterday) {
                return `${this.$t('chatHistory.yesterday')} ${hours}:${minutes}`;
            } else {
                const year = date.getFullYear();
                const month = (date.getMonth() + 1).toString().padStart(2, '0');
                const day = date.getDate().toString().padStart(2, '0');
                return `${year}-${month}-${day} ${hours}:${minutes}`;
            }
        },
        getAudioIconClass(message) {
            if (this.playingAudioId === message.audioId) {
                return 'el-icon-video-pause';
            }
            return 'el-icon-video-play';
        },
        stopAudio() {
            if (this.audioElement) {
                this.audioElement.pause();
                this.audioElement = null;
            }
            this.playingAudioId = null;
        },
        playAudio(message) {
            if (this.playingAudioId === message.audioId) {
                // 如果正在播放当前音频，则停止播放
                this.stopAudio();
                return;
            }

            // 停止当前正在播放的音频
            this.stopAudio();

            // 先获取音频下载ID
            this.playingAudioId = message.audioId;
            Api.agent.getAudioId(message.audioId, (res) => {
                if (this.playingAudioId !== message.audioId) return;
                if (res.data && res.data.data) {
                    // 使用获取到的下载ID播放音频（演示模式下播放本地生成的提示音）
                    this.audioElement = new Audio(playableUrl(Api.getServiceUrl() + `/agent/play/${res.data.data}`));

                    this.audioElement.onended = () => {
                        this.playingAudioId = null;
                        this.audioElement = null;
                    };

                    this.audioElement.play().catch(() => {
                        this.playingAudioId = null;
                        this.$message.warning(this.$t('xn.agents.chat.playFailed'));
                    });
                } else {
                    this.playingAudioId = null;
                }
            });
        },
        /** 头像色调：从 sessionId 中的数字求和取模，得到 1-5（原逻辑用于挑选头像图片） */
        getUserAvatar(sessionId) {
            const numbers = String(sessionId || '').match(/\d+/g);
            if (!numbers) return 1;
            const sum = numbers.reduce((acc, num) => acc + parseInt(num, 10), 0);
            return (sum % 5) + 1;
        },

        /** 演示模式：把会话整理成文本，作为下载文件内容（real 模式不调用） */
        transcriptOf(sessionsWithMessages) {
            const lines = [
                this.$t('xn.agents.chat.fileHeader', { name: this.agentName }),
                this.$t('xn.agents.chat.fileDemo'),
                '',
            ];
            sessionsWithMessages.forEach(({ session, messages }) => {
                lines.push(`== ${this.$t('xn.agents.chat.fileSession')} ${session.createdAt || ''} ==`);
                (messages || []).forEach((m) => {
                    const who = m.chatType === 1 ? this.$t('xn.agents.chat.fileUser') : this.agentName;
                    lines.push(`[${m.createdAt}] ${who}：${this.extractContentFromString(m.content)}`);
                });
                lines.push('');
            });
            return lines.join('\n');
        },
        fetchMessages(session) {
            return new Promise((resolve) => {
                Api.agent.getAgentChatHistory(this.agentId, session.sessionId, (res) => {
                    resolve({ session, messages: (res.data && res.data.data) || [] });
                });
            });
        },

        // 下载本会话聊天记录
        downloadCurrentSession() {
            Api.agent.getDownloadUrl(this.agentId, this.currentSessionId, (res) => {
                if (res && res.data && res.data.code === 0 && res.data.data) {
                    const uuid = res.data.data;
                    const url = `${Api.getServiceUrl()}/agent/chat-history/download/${uuid}/current`;
                    const session = this.sessions.find((s) => s.sessionId === this.currentSessionId) || { createdAt: '' };
                    openDownload(url, `${this.agentName}-${this.$t('xn.agents.chat.fileCurrent')}.txt`,
                        IS_MOCK ? this.transcriptOf([{ session, messages: this.messages }]) : '');
                } else {
                    this.$message.error(this.$t('chatHistory.downloadLinkFailed'));
                }
            });
        },

        // 下载本会话及前20条会话聊天记录
        downloadCurrentSessionWithPrevious() {
            Api.agent.getDownloadUrl(this.agentId, this.currentSessionId, (res) => {
                if (res && res.data && res.data.code === 0 && res.data.data) {
                    const uuid = res.data.data;
                    const url = `${Api.getServiceUrl()}/agent/chat-history/download/${uuid}/previous`;
                    const filename = `${this.agentName}-${this.$t('xn.agents.chat.filePrevious')}.txt`;
                    if (!IS_MOCK) {
                        openDownload(url, filename);
                        return;
                    }
                    // 演示：本会话 + 列表中排在它后面（更早）的最多 20 个已加载会话
                    const idx = this.sessions.findIndex((s) => s.sessionId === this.currentSessionId);
                    const picked = this.sessions.slice(Math.max(idx, 0), Math.max(idx, 0) + 21);
                    Promise.all(picked.map((s) => this.fetchMessages(s))).then((all) => {
                        openDownload(url, filename, this.transcriptOf(all));
                    });
                } else {
                    this.$message.error(this.$t('chatHistory.downloadLinkFailed'));
                }
            });
        }
    }
};
</script>

<style scoped>
.ch-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding-right: 32px; }
.ch-title__text { font-size: 18px; font-weight: 600; color: var(--xn-ink); }
.ch { display: grid; grid-template-columns: 240px minmax(0, 1fr); height: min(62vh, 620px); min-height: 360px; border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); overflow: hidden; }
.ch-sessions { position: relative; overflow-y: auto; padding: 8px; border-right: 1px solid var(--xn-line-2); background: var(--xn-mist-2); }
.ch-session {
  display: flex; align-items: center; gap: 10px; width: 100%; min-height: 48px; padding: 6px 10px; margin-bottom: 2px;
  border: 0; border-radius: var(--xn-r); background: none; font: inherit; color: var(--xn-ink); text-align: left; cursor: pointer;
}
.ch-session:hover { background: #fff; }
.ch-session.is-on { background: #fff; box-shadow: inset 0 0 0 1px var(--xn-line); }
.ch-session.is-on .ch-session__time { font-weight: 600; }
.ch-session__time { flex: 1; min-width: 0; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch-session__count { flex: none; min-width: 24px; height: 20px; padding: 0 6px; border-radius: 10px; background: var(--xn-line); color: var(--xn-ink-2); font-size: 12px; line-height: 20px; text-align: center; }
.ch-session.is-on .ch-session__count { background: var(--xn-lake-soft); color: var(--xn-lake-ink); }
.ch-more { margin: 6px 0; font-size: 13px; color: var(--xn-ink-3); text-align: center; }

.ch-ava { display: grid; place-items: center; flex: none; width: 32px; height: 32px; border-radius: 50%; font-size: 16px; }
.ch-ava--agent { background: var(--xn-ink); color: #fff; font: 600 14px/1 var(--xn-serif); }
.ch-ava--user { background: var(--xn-lake-soft); color: var(--xn-lake-ink); }
.ch-ava--user.tone-2 { background: #E6EFE9; color: #2F6A4B; }
.ch-ava--user.tone-3 { background: #F3ECDF; color: #7D5718; }
.ch-ava--user.tone-4 { background: #ECE8F1; color: #5A4A75; }
.ch-ava--user.tone-5 { background: #F2E6E2; color: #8A4535; }

.ch-content { position: relative; overflow-y: auto; padding: 16px 20px; background: #fff; }
.ch-messages { display: flex; flex-direction: column; gap: 14px; }
.ch-time { align-self: center; padding: 2px 10px; border-radius: 10px; background: var(--xn-mist-2); font-size: 12px; color: var(--xn-ink-3); }
.ch-msg { display: flex; align-items: flex-start; gap: 10px; max-width: 100%; }
.ch-msg--user { flex-direction: row-reverse; }
.ch-bubble {
  display: flex; align-items: flex-start; gap: 6px; max-width: min(72%, 560px); padding: 9px 12px;
  border-radius: 12px; background: var(--xn-mist); color: var(--xn-ink); font-size: 14px; line-height: 1.6;
}
.ch-msg--user .ch-bubble { background: var(--xn-ink); color: #fff; flex-direction: row-reverse; }
.ch-bubble__text { white-space: pre-wrap; word-break: break-word; }
.ch-play { display: grid; place-items: center; flex: none; width: 24px; height: 24px; margin: -1px 0; padding: 0; border: 0; border-radius: 50%; background: none; color: var(--xn-lake); cursor: pointer; }
.ch-play:hover { background: rgba(47, 111, 149, 0.12); }
.ch-msg--user .ch-play { color: #fff; }
.ch-msg--user .ch-play:hover { background: rgba(255, 255, 255, 0.16); }
.ch-pick { margin: 0; padding: 48px 0; text-align: center; color: var(--xn-ink-3); }

.ch-foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.ch-foot__note { margin-right: auto; font-size: 13px; }
.ch-foot .el-button + .el-button { margin-left: 0; }

@media (max-width: 760px) {
  .ch { grid-template-columns: 1fr; grid-template-rows: 160px minmax(0, 1fr); height: 70vh; }
  .ch-sessions { border-right: 0; border-bottom: 1px solid var(--xn-line-2); }
  .ch-bubble { max-width: 86%; }
}
</style>

<style>
.xn-chat-dialog { max-width: calc(100vw - 32px); margin-top: 6vh !important; }
.xn-chat-dialog .el-dialog__body { padding: 8px 24px 4px; }
</style>
