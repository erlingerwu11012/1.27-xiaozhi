package bailian

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
)

func voiceAllowed(catalogCSV string, extra []string, voice string) bool {
	if listHas(catalogCSV, voice) {
		return true
	}
	for _, item := range extra {
		if item == voice {
			return true
		}
	}
	return false
}

const MaxFrame = 128 * 1024

// Reject duplicate JSON keys so authorization and upstream parsing cannot differ.
func strictJSON(data []byte, out interface{}) error {
	if len(data) > MaxFrame || !utf8.Valid(data) {
		return errors.New("invalid_json")
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var visit func() error
	visit = func() error {
		tok, e := dec.Token()
		if e != nil {
			return e
		}
		d, ok := tok.(json.Delim)
		if !ok {
			return nil
		}
		switch d {
		case '{':
			keys := map[string]bool{}
			for dec.More() {
				k, e := dec.Token()
				if e != nil {
					return e
				}
				s, ok := k.(string)
				if !ok || keys[s] {
					return errors.New("duplicate_json_key")
				}
				keys[s] = true
				if e = visit(); e != nil {
					return e
				}
			}
		case '[':
			for dec.More() {
				if e := visit(); e != nil {
					return e
				}
			}
		default:
			return errors.New("invalid_json")
		}
		_, e = dec.Token()
		return e
	}
	if e := visit(); e != nil {
		return e
	}
	if _, e := dec.Token(); e != io.EOF {
		return errors.New("trailing_json")
	}
	dec = json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	return dec.Decode(out)
}

type TaskHeader struct {
	Action    string `json:"action,omitempty"`
	TaskID    string `json:"task_id"`
	Streaming string `json:"streaming,omitempty"`
}
type TaskPayload struct {
	Group      string          `json:"task_group,omitempty"`
	Task       string          `json:"task,omitempty"`
	Function   string          `json:"function,omitempty"`
	Model      string          `json:"model,omitempty"`
	Parameters json.RawMessage `json:"parameters,omitempty"`
	Input      json.RawMessage `json:"input"`
}
type TaskEvent struct {
	Header  TaskHeader  `json:"header"`
	Payload TaskPayload `json:"payload"`
}
type NativeState struct {
	Protocol, Model, TaskID, Voice   string
	SampleRate                       int
	Ready, Finishing, Canceled, SSML bool
	TextEvents                       int
	Units                            int64
	UsageSeen                        bool
	ConfirmedUnits                   int64
	HotFix                           json.RawMessage
}

func ParseRun(data []byte) (TaskEvent, error) {
	var ev TaskEvent
	e := strictJSON(data, &ev)
	if e != nil {
		return ev, e
	}
	if ev.Header.Action != "run-task" || ev.Header.Streaming != "duplex" || ev.Payload.Model == "" {
		return ev, errors.New("run_task_required")
	}
	if _, e = uuid.Parse(ev.Header.TaskID); e != nil {
		return ev, errors.New("invalid_task_id")
	}
	return ev, nil
}

func ConfigureTask(ev TaskEvent, cap Capability, extraVoices []string) (NativeState, error) {
	s := NativeState{Protocol: cap.Protocol, Model: cap.Model, TaskID: ev.Header.TaskID}
	if ev.Payload.Group != "audio" || ev.Payload.Model != cap.Model {
		return s, errors.New("task_model_mismatch")
	}
	var input map[string]json.RawMessage
	if e := strictJSON(ev.Payload.Input, &input); e != nil || len(input) != 0 {
		return s, errors.New("empty_run_input_required")
	}
	if cap.Protocol == "asr_inference" {
		if ev.Payload.Task != "asr" || ev.Payload.Function != "recognition" {
			return s, errors.New("invalid_asr_task")
		}
		var params struct {
			Format              string   `json:"format"`
			SampleRate          int      `json:"sample_rate"`
			LanguageHints       []string `json:"language_hints,omitempty"`
			SemanticPunctuation bool     `json:"semantic_punctuation_enabled,omitempty"`
			Silence             int      `json:"max_sentence_silence,omitempty"`
		}
		if e := strictJSON(ev.Payload.Parameters, &params); e != nil {
			return s, e
		}
		if params.Format != "pcm" || (params.SampleRate != 16000 && params.SampleRate != 8000) {
			return s, errors.New("pcm_8000_or_16000_required")
		}
		s.SampleRate = params.SampleRate
	} else if cap.Protocol == "tts_inference" {
		if ev.Payload.Task != "tts" || ev.Payload.Function != "SpeechSynthesizer" {
			return s, errors.New("invalid_tts_task")
		}
		var params struct {
			TextType        string          `json:"text_type"`
			Voice           string          `json:"voice"`
			Format          string          `json:"format,omitempty"`
			SampleRate      int             `json:"sample_rate,omitempty"`
			Volume          *int            `json:"volume,omitempty"`
			Rate            *float64        `json:"rate,omitempty"`
			Pitch           *float64        `json:"pitch,omitempty"`
			SSML            bool            `json:"enable_ssml,omitempty"`
			WordTimestamp   bool            `json:"word_timestamp_enabled,omitempty"`
			Seed            *int            `json:"seed,omitempty"`
			Instruction     string          `json:"instruction,omitempty"`
			LanguageHints   []string        `json:"language_hints,omitempty"`
			HotFix          json.RawMessage `json:"hot_fix,omitempty"`
			EnableAIGC      bool            `json:"enable_aigc_tag,omitempty"`
			AIGCPropagator  string          `json:"aigc_propagator,omitempty"`
			AIGCPropagateID string          `json:"aigc_propagate_id,omitempty"`
			BitRate         *int            `json:"bit_rate,omitempty"`
		}
		if e := strictJSON(ev.Payload.Parameters, &params); e != nil {
			return s, e
		}
		if params.WordTimestamp || params.Seed != nil {
			return s, errors.New("excluded_tts_parameter")
		}
		if params.TextType != "PlainText" || params.Voice == "" || !voiceAllowed(cap.Voices, extraVoices, params.Voice) {
			return s, errors.New("verified_voice_required")
		}
		switch params.Format {
		case "", "mp3", "pcm", "wav", "opus":
		default:
			return s, errors.New("invalid_format")
		}
		switch params.SampleRate {
		case 0, 8000, 16000, 22050, 24000, 44100, 48000:
		default:
			return s, errors.New("invalid_sample_rate")
		}
		if params.Volume != nil && (*params.Volume < 0 || *params.Volume > 100) || params.Rate != nil && (*params.Rate < 0.5 || *params.Rate > 2) || params.Pitch != nil && (*params.Pitch < 0.5 || *params.Pitch > 2) {
			return s, errors.New("invalid_tts_parameters")
		}
		if len(params.Instruction) > 100 {
			return s, errors.New("instruction_too_long")
		}
		if len(params.LanguageHints) > 1 {
			return s, errors.New("language_hints_invalid")
		}
		if len(params.LanguageHints) == 1 && !listHas(strings.Join([]string{
			"zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi", "es", "it", "ms", "fil", "ar",
		}, ","), params.LanguageHints[0]) {
			return s, errors.New("language_hint_not_supported")
		}
		if e := validateBitRateKBPS(params.Format, params.BitRate); e != nil {
			return s, e
		}
		format := params.Format
		if format == "" {
			format = "pcm"
		}
		if params.EnableAIGC && format == "pcm" {
			return s, errors.New("aigc_not_supported_for_format")
		}
		if len(params.HotFix) > 0 {
			canon, e := CanonicalHotFixJSON(params.HotFix)
			if e != nil {
				return s, e
			}
			s.HotFix = canon
		}
		s.SSML = params.SSML
		s.Voice = params.Voice
	} else {
		return s, errors.New("invalid_protocol")
	}
	return s, nil
}

func rewriteCanonicalTTSParams(ev *TaskEvent, state NativeState) error {
	if len(state.HotFix) == 0 {
		return nil
	}
	var params map[string]json.RawMessage
	if json.Unmarshal(ev.Payload.Parameters, &params) != nil {
		return errors.New("invalid_task_configuration")
	}
	params["hot_fix"] = state.HotFix
	raw, e := json.Marshal(params)
	if e != nil {
		return e
	}
	ev.Payload.Parameters = raw
	return nil
}

func (s *NativeState) Client(kind int, data []byte) error {
	if !s.Ready || s.Finishing {
		return errors.New("task_not_ready")
	}
	if kind == 2 {
		if s.Protocol != "asr_inference" || len(data) == 0 || len(data)%2 != 0 || len(data) > s.SampleRate*2 {
			return errors.New("invalid_pcm_chunk")
		}
		if s.Units+int64(len(data)) > int64(s.SampleRate*2*300) {
			return errors.New("audio_limit")
		}
		s.Units += int64(len(data))
		return nil
	}
	if kind != 1 {
		return errors.New("invalid_frame")
	}
	var ev TaskEvent
	if e := strictJSON(data, &ev); e != nil {
		return e
	}
	if ev.Header.TaskID != s.TaskID || ev.Header.Streaming != "duplex" {
		return errors.New("task_id_mismatch")
	}
	if ev.Payload.Model != "" || ev.Payload.Group != "" || ev.Payload.Task != "" || ev.Payload.Function != "" || len(ev.Payload.Parameters) != 0 {
		return errors.New("immutable_task")
	}
	if ev.Header.Action == "finish-task" {
		var input map[string]json.RawMessage
		if e := strictJSON(ev.Payload.Input, &input); e != nil {
			return errors.New("normal_finish_only")
		}
		if len(input) == 0 {
			s.Finishing = true
			return nil
		}
		if len(input) == 1 {
			var directive struct {
				Directive string `json:"directive"`
			}
			if e := strictJSON(ev.Payload.Input, &directive); e == nil && directive.Directive == "cancel" {
				s.Finishing = true
				s.Canceled = true
				return nil
			}
		}
		return errors.New("normal_finish_only")
	}
	if ev.Header.Action != "continue-task" || s.Protocol != "tts_inference" {
		return errors.New("event_not_allowed")
	}
	var input struct {
		Text string `json:"text"`
	}
	if e := strictJSON(ev.Payload.Input, &input); e != nil {
		return e
	}
	if input.Text == "" || utf8.RuneCountInString(input.Text) > 20000 || (s.SSML && s.TextEvents != 0) {
		return errors.New("text_limit")
	}
	n, e := EstimateSpeechUnits(input.Text, s.SSML, s.HotFix)
	if e != nil {
		return e
	}
	if n+s.Units > 200000 {
		return errors.New("task_text_limit")
	}
	s.Units += n
	s.TextEvents++
	return nil
}

// Units upper bound incorporates the ASR provider's integer-second usage.
func (s NativeState) Ceiling(p Price) (int64, error) {
	if s.Protocol == "asr_inference" {
		den := int64(s.SampleRate * 2)
		return p.Quota((s.Units+den-1)/den, 1)
	}
	return p.Quota(s.Units, 1)
}

func (s *NativeState) Server(data []byte) (string, error) {
	var ev struct {
		Header struct {
			Event  string `json:"event"`
			TaskID string `json:"task_id"`
		} `json:"header"`
		Payload struct {
			Usage *struct {
				Characters *int64 `json:"characters"`
				Duration   *int64 `json:"duration"`
			} `json:"usage"`
		} `json:"payload"`
	}
	if json.Unmarshal(data, &ev) != nil || ev.Header.TaskID != s.TaskID {
		return "", errors.New("invalid_upstream_event")
	}
	switch ev.Header.Event {
	case "task-started":
		if s.Ready {
			return "", errors.New("duplicate_task_started")
		}
		s.Ready = true
	case "result-generated":
		if !s.Ready {
			return "", errors.New("task_not_ready")
		}
	case "task-finished":
		if !s.Finishing {
			return "", errors.New("unexpected_task_finish")
		}
	case "task-failed":
		return "", errors.New("upstream_task_failed")
	default:
		return "", errors.New("unsupported_upstream_event")
	}
	if ev.Payload.Usage != nil {
		units := ev.Payload.Usage.Characters
		if s.Protocol == "asr_inference" {
			units = ev.Payload.Usage.Duration
		}
		if units != nil {
			if *units < s.ConfirmedUnits || *units < 0 {
				return "", errors.New("invalid_upstream_usage")
			}
			s.UsageSeen = true
			s.ConfirmedUnits = *units
		}
	}
	return ev.Header.Event, nil
}

type ASRState struct {
	RequestID                    string
	Rate                         int
	Configured, Ready, Finishing bool
	Bytes                        int64
	UsageSeen                    bool
	ConfirmedSeconds             int64
}

func (s *ASRState) Client(data []byte) error {
	var ev struct {
		Type    string          `json:"type"`
		EventID string          `json:"event_id,omitempty"`
		Audio   string          `json:"audio,omitempty"`
		Session json.RawMessage `json:"session,omitempty"`
	}
	if e := strictJSON(data, &ev); e != nil {
		return e
	}
	if s.Finishing {
		return errors.New("session_finishing")
	}
	switch ev.Type {
	case "session.update":
		if s.Configured {
			return errors.New("immutable_session")
		}
		var p struct {
			Format        string          `json:"input_audio_format"`
			Rate          int             `json:"sample_rate"`
			Modalities    []string        `json:"modalities"`
			Transcription json.RawMessage `json:"input_audio_transcription,omitempty"`
			TurnDetection json.RawMessage `json:"turn_detection,omitempty"`
		}
		if e := strictJSON(ev.Session, &p); e != nil {
			return e
		}
		if p.Format != "pcm" || (p.Rate != 8000 && p.Rate != 16000) || len(p.Modalities) != 1 || p.Modalities[0] != "text" {
			return errors.New("invalid_asr_session")
		}
		s.Rate = p.Rate
		s.Configured = true
	case "input_audio_buffer.append":
		if !s.Ready {
			return errors.New("session_not_ready")
		}
		raw, e := base64.StdEncoding.Strict().DecodeString(ev.Audio)
		if e != nil || len(raw) == 0 || len(raw)%2 != 0 || len(raw) > s.Rate*2 {
			return errors.New("invalid_pcm")
		}
		if s.Bytes+int64(len(raw)) > int64(s.Rate*2*300) {
			return errors.New("audio_limit")
		}
		s.Bytes += int64(len(raw))
	case "input_audio_buffer.commit":
		if !s.Ready {
			return errors.New("session_not_ready")
		}
	case "session.finish":
		if !s.Ready {
			return errors.New("session_not_ready")
		}
		s.Finishing = true
	default:
		return errors.New("event_not_allowed")
	}
	if ev.Type != "session.update" && len(ev.Session) > 0 {
		return errors.New("unexpected_session")
	}
	return nil
}
func (s *ASRState) Server(data []byte) (string, error) {
	var ev struct {
		Type  string `json:"type"`
		Usage *struct {
			Duration *int64 `json:"duration"`
		} `json:"usage,omitempty"`
		Payload struct {
			Usage *struct {
				Duration *int64 `json:"duration"`
			} `json:"usage,omitempty"`
		} `json:"payload,omitempty"`
		Session struct {
			ID     string `json:"id"`
			Model  string `json:"model"`
			Rate   int    `json:"sample_rate"`
			Format string `json:"input_audio_format"`
		} `json:"session"`
	}
	if json.Unmarshal(data, &ev) != nil {
		return "", errors.New("invalid_upstream_json")
	}
	if ev.Type == "session.created" && ev.Session.ID != "" {
		s.RequestID = ev.Session.ID
	}
	if ev.Usage != nil && ev.Usage.Duration != nil {
		if ev.Payload.Usage != nil && ev.Payload.Usage.Duration != nil && *ev.Payload.Usage.Duration != *ev.Usage.Duration {
			return "", errors.New("conflicting_upstream_usage")
		}
		ev.Payload.Usage = ev.Usage
	}
	if ev.Type == "error" || strings.HasSuffix(ev.Type, ".failed") {
		return "", errors.New("upstream_asr_error")
	}
	if ev.Type == "session.updated" {
		if !s.Configured || s.Ready || ev.Session.Model != "" && ev.Session.Model != "qwen3-asr-flash-realtime" || ev.Session.Rate != 0 && ev.Session.Rate != s.Rate || (ev.Session.Format != "pcm" && ev.Session.Format != "pcm16") {
			return "", errors.New("upstream_session_mismatch")
		}
		s.Ready = true
	}
	if ev.Type == "session.finished" && !s.Finishing {
		return "", errors.New("unexpected_finish")
	}
	if ev.Payload.Usage != nil && ev.Payload.Usage.Duration != nil {
		if *ev.Payload.Usage.Duration < s.ConfirmedSeconds || *ev.Payload.Usage.Duration < 0 {
			return "", errors.New("invalid_upstream_usage")
		}
		s.UsageSeen = true
		s.ConfirmedSeconds = *ev.Payload.Usage.Duration
	}
	return ev.Type, nil
}
