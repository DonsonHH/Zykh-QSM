package main

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"crypto/tls"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"strings"
	"time"
)

type result map[string]any

func main() {
	if len(os.Args) < 2 {
		writeJSON(os.Stdout, result{"ok": false, "error": "usage: zykh-ai-voice asr|tts"})
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "asr":
		err = runASR(os.Args[2:])
	case "tts":
		err = runTTS(os.Args[2:])
	default:
		err = fmt.Errorf("unknown command %s", os.Args[1])
	}
	if err != nil {
		writeJSON(os.Stdout, result{"ok": false, "error": err.Error()})
		os.Exit(1)
	}
}

func runASR(args []string) error {
	fs := flag.NewFlagSet("asr", flag.ContinueOnError)
	input := fs.String("input", "", "input wav/pcm file")
	output := fs.String("output", "", "output json")
	model := fs.String("model", "fun-asr-flash-8k-realtime", "asr model")
	sampleRate := fs.Int("sample-rate", 8000, "pcm sample rate")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *input == "" {
		return errors.New("missing --input")
	}
	key := apiKey()
	if key == "" {
		return errors.New("DASHSCOPE_API_KEY is empty")
	}
	pcm, err := loadMonoPCM(*input, *sampleRate)
	if err != nil {
		return err
	}
	wsURL := getenv("ASR_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference/")
	conn, status, err := dialWebSocket(wsURL, map[string]string{
		"Authorization":              "bearer " + key,
		"X-DashScope-DataInspection": "enable",
	})
	if err != nil {
		if status != 0 {
			return fmt.Errorf("websocket dial failed http=%d: %w", status, err)
		}
		return err
	}
	defer conn.Close()

	taskID := uuid()
	runTask := result{
		"header": result{"action": "run-task", "task_id": taskID, "streaming": "duplex"},
		"payload": result{
			"task_group": "audio",
			"task":       "asr",
			"function":   "SpeechRecognizer",
			"model":      *model,
			"parameters": result{
				"format":      "pcm",
				"sample_rate": *sampleRate,
				"language":    "zh",
			},
			"input": result{},
		},
	}
	if err := conn.WriteJSON(runTask); err != nil {
		return err
	}
	deadline := time.Now().Add(35 * time.Second)
	_ = conn.SetReadDeadline(deadline)
	textCh := make(chan string, 8)
	errCh := make(chan error, 1)
	go readASR(conn, textCh, errCh)

	chunkBytes := *sampleRate / 10 * 2
	for off := 0; off < len(pcm); off += chunkBytes {
		end := off + chunkBytes
		if end > len(pcm) {
			end = len(pcm)
		}
		if err := conn.WriteMessage(wsBinary, pcm[off:end]); err != nil {
			return err
		}
		time.Sleep(80 * time.Millisecond)
	}
	finishTask := result{"header": result{"action": "finish-task", "task_id": taskID}, "payload": result{"input": result{}}}
	_ = conn.WriteJSON(finishTask)

	var transcript strings.Builder
	timeout := time.NewTimer(12 * time.Second)
	defer timeout.Stop()
	for {
		select {
		case s := <-textCh:
			if strings.TrimSpace(s) != "" {
				if transcript.Len() > 0 {
					transcript.WriteString(" ")
				}
				transcript.WriteString(strings.TrimSpace(s))
			}
		case err := <-errCh:
			if err != nil && transcript.Len() == 0 {
				return err
			}
			out := result{"ok": transcript.Len() > 0, "text": strings.TrimSpace(transcript.String()), "model": *model, "task_id": taskID}
			return writeResult(*output, out)
		case <-timeout.C:
			out := result{"ok": transcript.Len() > 0, "text": strings.TrimSpace(transcript.String()), "model": *model, "task_id": taskID, "timeout": true}
			return writeResult(*output, out)
		}
	}
}

func readASR(conn *wsConn, textCh chan<- string, errCh chan<- error) {
	defer close(textCh)
	for {
		typ, msg, err := conn.ReadMessage()
		if err != nil {
			errCh <- nil
			return
		}
		if typ != wsText {
			continue
		}
		var obj map[string]any
		if json.Unmarshal(msg, &obj) != nil {
			continue
		}
		if e, ok := obj["error"].(map[string]any); ok {
			errCh <- fmt.Errorf("%v", e)
			return
		}
		if payload, ok := obj["payload"]; ok {
			for _, s := range collectStrings(payload, []string{"text", "sentence", "transcript", "result"}) {
				textCh <- s
			}
		}
		if header, ok := obj["header"].(map[string]any); ok {
			event := fmt.Sprint(header["event"])
			if strings.Contains(event, "task-finished") || strings.Contains(event, "task-failed") {
				errCh <- nil
				return
			}
		}
	}
}

func runTTS(args []string) error {
	fs := flag.NewFlagSet("tts", flag.ContinueOnError)
	text := fs.String("text", "", "text to synthesize")
	output := fs.String("output", "", "output wav")
	model := fs.String("model", "qwen3-tts-instruct-flash-realtime", "tts model")
	voice := fs.String("voice", "Cherry", "voice")
	instructions := fs.String("instructions", "面向老人，语速稍慢，语气温和清晰。", "voice instructions")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if strings.TrimSpace(*text) == "" {
		return errors.New("missing --text")
	}
	if *output == "" {
		return errors.New("missing --output")
	}
	key := apiKey()
	if key == "" {
		return errors.New("DASHSCOPE_API_KEY is empty")
	}
	u := getenv("TTS_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
	if !strings.Contains(u, "?") {
		u += "?model=" + url.QueryEscape(*model)
	}
	conn, status, err := dialWebSocket(u, map[string]string{
		"Authorization":              "bearer " + key,
		"X-DashScope-DataInspection": "enable",
	})
	if err != nil {
		if status != 0 {
			return fmt.Errorf("websocket dial failed http=%d: %w", status, err)
		}
		return err
	}
	defer conn.Close()

	events := []result{
		{"type": "session.update", "event_id": uuid(), "session": result{
			"voice":           *voice,
			"response_format": "pcm",
			"sample_rate":     24000,
			"mode":            "commit",
			"instructions":    *instructions,
		}},
		{"type": "input_text_buffer.append", "event_id": uuid(), "text": *text},
		{"type": "input_text_buffer.commit", "event_id": uuid()},
	}
	for _, e := range events {
		if err := conn.WriteJSON(e); err != nil {
			return err
		}
	}

	var pcm bytes.Buffer
	_ = conn.SetReadDeadline(time.Now().Add(35 * time.Second))
	for {
		typ, msg, err := conn.ReadMessage()
		if err != nil {
			break
		}
		if typ != wsText {
			continue
		}
		var obj map[string]any
		if json.Unmarshal(msg, &obj) != nil {
			continue
		}
		switch fmt.Sprint(obj["type"]) {
		case "response.audio.delta":
			if s, ok := obj["delta"].(string); ok {
				b, _ := base64.StdEncoding.DecodeString(s)
				pcm.Write(b)
			}
		case "response.done", "session.finished":
			goto done
		case "error":
			return fmt.Errorf("%v", obj["error"])
		}
	}
done:
	if pcm.Len() == 0 {
		return errors.New("tts returned empty audio")
	}
	if err := writeWAV(*output, pcm.Bytes(), 24000); err != nil {
		return err
	}
	_ = conn.WriteJSON(result{"type": "session.finish", "event_id": uuid()})
	return writeResult("", result{"ok": true, "mode": "qwen-tts", "model": *model, "voice": *voice, "file": *output, "bytes": pcm.Len()})
}

const (
	wsText   = 1
	wsBinary = 2
	wsClose  = 8
	wsPing   = 9
	wsPong   = 10
)

type wsConn struct {
	c net.Conn
}

func dialWebSocket(rawURL string, headers map[string]string) (*wsConn, int, error) {
	u, err := url.Parse(rawURL)
	if err != nil {
		return nil, 0, err
	}
	host := u.Host
	if !strings.Contains(host, ":") {
		if u.Scheme == "wss" {
			host += ":443"
		} else {
			host += ":80"
		}
	}
	var c net.Conn
	if u.Scheme == "wss" {
		c, err = tls.Dial("tcp", host, &tls.Config{ServerName: u.Hostname()})
	} else {
		c, err = net.Dial("tcp", host)
	}
	if err != nil {
		return nil, 0, err
	}
	keyBytes := make([]byte, 16)
	_, _ = rand.Read(keyBytes)
	key := base64.StdEncoding.EncodeToString(keyBytes)
	path := u.RequestURI()
	if path == "" {
		path = "/"
	}
	var req strings.Builder
	req.WriteString("GET " + path + " HTTP/1.1\r\n")
	req.WriteString("Host: " + u.Host + "\r\n")
	req.WriteString("Upgrade: websocket\r\n")
	req.WriteString("Connection: Upgrade\r\n")
	req.WriteString("Sec-WebSocket-Version: 13\r\n")
	req.WriteString("Sec-WebSocket-Key: " + key + "\r\n")
	for k, v := range headers {
		req.WriteString(k + ": " + v + "\r\n")
	}
	req.WriteString("\r\n")
	if _, err := io.WriteString(c, req.String()); err != nil {
		_ = c.Close()
		return nil, 0, err
	}
	br := bufio.NewReader(c)
	statusLine, err := br.ReadString('\n')
	if err != nil {
		_ = c.Close()
		return nil, 0, err
	}
	status := 0
	_, _ = fmt.Sscanf(statusLine, "HTTP/1.1 %d", &status)
	for {
		line, err := br.ReadString('\n')
		if err != nil {
			_ = c.Close()
			return nil, status, err
		}
		if line == "\r\n" {
			break
		}
	}
	if status != 101 {
		_ = c.Close()
		return nil, status, fmt.Errorf(strings.TrimSpace(statusLine))
	}
	if br.Buffered() > 0 {
		c = &bufferedConn{Conn: c, r: br}
	}
	return &wsConn{c: c}, status, nil
}

func (w *wsConn) Close() error {
	_ = w.WriteMessage(wsClose, []byte{})
	return w.c.Close()
}

func (w *wsConn) SetReadDeadline(t time.Time) error {
	return w.c.SetReadDeadline(t)
}

func (w *wsConn) WriteJSON(v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return w.WriteMessage(wsText, b)
}

func (w *wsConn) WriteMessage(opcode int, payload []byte) error {
	var h bytes.Buffer
	h.WriteByte(0x80 | byte(opcode))
	n := len(payload)
	maskBit := byte(0x80)
	switch {
	case n < 126:
		h.WriteByte(maskBit | byte(n))
	case n <= 65535:
		h.WriteByte(maskBit | 126)
		_ = binary.Write(&h, binary.BigEndian, uint16(n))
	default:
		h.WriteByte(maskBit | 127)
		_ = binary.Write(&h, binary.BigEndian, uint64(n))
	}
	var mask [4]byte
	_, _ = rand.Read(mask[:])
	h.Write(mask[:])
	frame := make([]byte, len(payload))
	for i, b := range payload {
		frame[i] = b ^ mask[i%4]
	}
	if _, err := w.c.Write(h.Bytes()); err != nil {
		return err
	}
	_, err := w.c.Write(frame)
	return err
}

func (w *wsConn) ReadMessage() (int, []byte, error) {
	for {
		var h [2]byte
		if _, err := io.ReadFull(w.c, h[:]); err != nil {
			return 0, nil, err
		}
		opcode := int(h[0] & 0x0f)
		masked := h[1]&0x80 != 0
		n := uint64(h[1] & 0x7f)
		if n == 126 {
			var b [2]byte
			if _, err := io.ReadFull(w.c, b[:]); err != nil {
				return 0, nil, err
			}
			n = uint64(binary.BigEndian.Uint16(b[:]))
		} else if n == 127 {
			var b [8]byte
			if _, err := io.ReadFull(w.c, b[:]); err != nil {
				return 0, nil, err
			}
			n = binary.BigEndian.Uint64(b[:])
		}
		var mask [4]byte
		if masked {
			if _, err := io.ReadFull(w.c, mask[:]); err != nil {
				return 0, nil, err
			}
		}
		payload := make([]byte, n)
		if _, err := io.ReadFull(w.c, payload); err != nil {
			return 0, nil, err
		}
		if masked {
			for i := range payload {
				payload[i] ^= mask[i%4]
			}
		}
		if opcode == wsPing {
			_ = w.WriteMessage(wsPong, payload)
			continue
		}
		if opcode == wsClose {
			return opcode, payload, io.EOF
		}
		return opcode, payload, nil
	}
}

type bufferedConn struct {
	net.Conn
	r *bufio.Reader
}

func (b *bufferedConn) Read(p []byte) (int, error) {
	return b.r.Read(p)
}

func loadMonoPCM(path string, targetRate int) ([]byte, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) < 44 || string(data[:4]) != "RIFF" || string(data[8:12]) != "WAVE" {
		return data, nil
	}
	channels := int(binary.LittleEndian.Uint16(data[22:24]))
	rate := int(binary.LittleEndian.Uint32(data[24:28]))
	bits := int(binary.LittleEndian.Uint16(data[34:36]))
	if bits != 16 {
		return nil, fmt.Errorf("unsupported wav bits=%d", bits)
	}
	pos := 12
	for pos+8 <= len(data) {
		id := string(data[pos : pos+4])
		size := int(binary.LittleEndian.Uint32(data[pos+4 : pos+8]))
		pos += 8
		if id == "data" {
			pcm := data[pos:min(pos+size, len(data))]
			return normalizePCM16(pcm, channels, rate, targetRate), nil
		}
		pos += size
	}
	return nil, errors.New("wav data chunk not found")
}

func normalizePCM16(pcm []byte, channels, rate, targetRate int) []byte {
	if channels <= 0 {
		channels = 1
	}
	var mono []int16
	frame := channels * 2
	for i := 0; i+frame <= len(pcm); i += frame {
		sum := 0
		for ch := 0; ch < channels; ch++ {
			sum += int(int16(binary.LittleEndian.Uint16(pcm[i+ch*2 : i+ch*2+2])))
		}
		mono = append(mono, int16(sum/channels))
	}
	if rate > 0 && targetRate > 0 && rate != targetRate {
		step := float64(rate) / float64(targetRate)
		var down []int16
		for x := 0.0; int(x) < len(mono); x += step {
			down = append(down, mono[int(x)])
		}
		mono = down
	}
	out := make([]byte, len(mono)*2)
	for i, v := range mono {
		binary.LittleEndian.PutUint16(out[i*2:], uint16(v))
	}
	return out
}

func writeWAV(path string, pcm []byte, rate int) error {
	var b bytes.Buffer
	b.WriteString("RIFF")
	_ = binary.Write(&b, binary.LittleEndian, uint32(36+len(pcm)))
	b.WriteString("WAVEfmt ")
	_ = binary.Write(&b, binary.LittleEndian, uint32(16))
	_ = binary.Write(&b, binary.LittleEndian, uint16(1))
	_ = binary.Write(&b, binary.LittleEndian, uint16(1))
	_ = binary.Write(&b, binary.LittleEndian, uint32(rate))
	_ = binary.Write(&b, binary.LittleEndian, uint32(rate*2))
	_ = binary.Write(&b, binary.LittleEndian, uint16(2))
	_ = binary.Write(&b, binary.LittleEndian, uint16(16))
	b.WriteString("data")
	_ = binary.Write(&b, binary.LittleEndian, uint32(len(pcm)))
	b.Write(pcm)
	return os.WriteFile(path, b.Bytes(), 0600)
}

func collectStrings(v any, keys []string) []string {
	var out []string
	switch x := v.(type) {
	case map[string]any:
		for _, k := range keys {
			if s, ok := x[k].(string); ok && strings.TrimSpace(s) != "" {
				out = append(out, s)
			}
		}
		for _, child := range x {
			out = append(out, collectStrings(child, keys)...)
		}
	case []any:
		for _, child := range x {
			out = append(out, collectStrings(child, keys)...)
		}
	}
	return unique(out)
}

func unique(in []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range in {
		s = strings.TrimSpace(s)
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}

func writeResult(path string, v result) error {
	if path != "" {
		f, err := os.Create(path)
		if err != nil {
			return err
		}
		defer f.Close()
		return writeJSON(f, v)
	}
	return writeJSON(os.Stdout, v)
}

func writeJSON(w io.Writer, v result) error {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

func apiKey() string {
	if v := os.Getenv("DASHSCOPE_API_KEY"); strings.TrimSpace(v) != "" {
		return strings.TrimSpace(v)
	}
	if f := os.Getenv("DASHSCOPE_API_KEY_FILE"); f != "" {
		b, _ := os.ReadFile(f)
		return strings.TrimSpace(string(b))
	}
	return ""
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func uuid() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		binary.BigEndian.Uint32(b[0:4]),
		binary.BigEndian.Uint16(b[4:6]),
		binary.BigEndian.Uint16(b[6:8]),
		binary.BigEndian.Uint16(b[8:10]),
		b[10:16])
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
