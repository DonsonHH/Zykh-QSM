#include "sherpa-onnx/c-api/c-api.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

volatile sig_atomic_t running = 1;

void Stop(int) { running = 0; }

bool WriteAll(int fd, const void *data, size_t size) {
  const char *bytes = static_cast<const char *>(data);
  while (size > 0) {
    const ssize_t written = send(fd, bytes, size, MSG_NOSIGNAL);
    if (written <= 0) return false;
    bytes += written;
    size -= static_cast<size_t>(written);
  }
  return true;
}

bool ReadLine(int fd, std::string *line) {
  line->clear();
  char ch = 0;
  while (line->size() < 512) {
    const ssize_t count = recv(fd, &ch, 1, 0);
    if (count <= 0) return false;
    if (ch == '\n') return true;
    if (ch != '\r') line->push_back(ch);
  }
  return false;
}

bool ReadBytes(int fd, size_t size, std::string *out) {
  out->assign(size, '\0');
  size_t offset = 0;
  while (offset < size) {
    const ssize_t count = recv(fd, out->data() + offset, size - offset, 0);
    if (count <= 0) return false;
    offset += static_cast<size_t>(count);
  }
  return true;
}

struct Playback {
  FILE *pipe = nullptr;
  std::chrono::steady_clock::time_point started;
  long first_audio_ms = -1;
  int64_t samples = 0;
};

int32_t PlayChunk(const float *samples, int32_t count, float, void *arg) {
  auto *playback = static_cast<Playback *>(arg);
  if (!playback || !playback->pipe || !samples || count <= 0) return 0;
  if (playback->first_audio_ms < 0) {
    playback->first_audio_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - playback->started).count();
  }
  std::vector<int16_t> pcm(static_cast<size_t>(count));
  for (int32_t index = 0; index < count; ++index) {
    const float value = std::clamp(samples[index], -1.0f, 1.0f);
    pcm[static_cast<size_t>(index)] = static_cast<int16_t>(std::lrint(value * 32767.0f));
  }
  if (fwrite(pcm.data(), sizeof(int16_t), pcm.size(), playback->pipe) != pcm.size()) return 0;
  fflush(playback->pipe);
  playback->samples += count;
  return 1;
}

void SendError(int fd, const char *error) {
  const std::string body = std::string("{\"ok\":false,\"error\":\"") + error + "\"}\n";
  WriteAll(fd, body.data(), body.size());
}

bool HandleClient(int fd, const SherpaOnnxOfflineTts *tts, int sample_rate) {
  std::string header;
  if (!ReadLine(fd, &header)) return false;

  float speed = 1.32f;
  int volume = 230;
  size_t text_size = 0;
  if (std::sscanf(header.c_str(), "%f\t%d\t%zu", &speed, &volume, &text_size) != 3 ||
      text_size == 0 || text_size > 8192) {
    SendError(fd, "invalid request");
    return false;
  }
  speed = std::clamp(speed, 0.75f, 2.0f);
  volume = std::clamp(volume, 0, 255);

  std::string text;
  if (!ReadBytes(fd, text_size, &text)) {
    SendError(fd, "incomplete text");
    return false;
  }

  char mixer[256];
  std::snprintf(mixer, sizeof(mixer),
                "amixer -q -c 0 cset numid=1 2; amixer -q -c 0 cset numid=5 %d,%d",
                volume, volume);
  const int mixer_status = std::system(mixer);
  (void)mixer_status;

  char player[256];
  std::snprintf(player, sizeof(player),
                "aplay -q -D plughw:0,0 -t raw -f S16_LE -r %d -c 1", sample_rate);
  Playback playback;
  playback.pipe = popen(player, "w");
  playback.started = std::chrono::steady_clock::now();
  if (!playback.pipe) {
    SendError(fd, "speaker unavailable");
    return false;
  }

  SherpaOnnxGenerationConfig generation{};
  generation.speed = speed;
  generation.sid = 0;
  generation.silence_scale = 0.15f;
  const SherpaOnnxGeneratedAudio *audio = SherpaOnnxOfflineTtsGenerateWithConfig(
      tts, text.c_str(), &generation, PlayChunk, &playback);
  const int play_status = pclose(playback.pipe);
  playback.pipe = nullptr;
  const long total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - playback.started).count();

  if (!audio || play_status != 0) {
    if (audio) SherpaOnnxDestroyOfflineTtsGeneratedAudio(audio);
    SendError(fd, audio ? "speaker playback failed" : "synthesis failed");
    return false;
  }
  SherpaOnnxDestroyOfflineTtsGeneratedAudio(audio);

  char response[320];
  std::snprintf(response, sizeof(response),
                "{\"ok\":true,\"mode\":\"offline-sherpa-onnx-stream\","
                "\"sample_rate\":%d,\"samples\":%lld,\"first_audio_ms\":%ld,"
                "\"total_ms\":%ld,\"speed\":%.2f}\n",
                sample_rate, static_cast<long long>(playback.samples), playback.first_audio_ms,
                total_ms, speed);
  return WriteAll(fd, response, std::strlen(response));
}

}  // namespace

int main(int argc, char **argv) {
  const char *root = argc > 1 ? argv[1] : "/userdata/zykh_voice";
  const int port = argc > 2 ? std::atoi(argv[2]) : 19002;
  std::string model = std::string(root) + "/models/tts/zh_CN-xiao_ya-medium.onnx";
  std::string lexicon = std::string(root) + "/models/tts/lexicon.txt";
  std::string tokens = std::string(root) + "/models/tts/tokens.txt";
  std::string rules = std::string(root) + "/models/tts/phone.fst," + root +
                      "/models/tts/date.fst," + root + "/models/tts/number.fst";

  SherpaOnnxOfflineTtsConfig config{};
  config.model.vits.model = model.c_str();
  config.model.vits.lexicon = lexicon.c_str();
  config.model.vits.tokens = tokens.c_str();
  config.model.vits.noise_scale = 0.667f;
  config.model.vits.noise_scale_w = 0.8f;
  config.model.vits.length_scale = 1.0f;
  config.model.num_threads = 2;
  config.model.provider = "cpu";
  config.rule_fsts = rules.c_str();
  config.max_num_sentences = 1;
  config.silence_scale = 0.15f;

  const SherpaOnnxOfflineTts *tts = SherpaOnnxCreateOfflineTts(&config);
  if (!tts) {
    std::fprintf(stderr, "local-tts: failed to load model\n");
    return 2;
  }
  const int sample_rate = SherpaOnnxOfflineTtsSampleRate(tts);

  signal(SIGTERM, Stop);
  signal(SIGINT, Stop);
  signal(SIGPIPE, SIG_IGN);

  const int server = socket(AF_INET, SOCK_STREAM, 0);
  int reuse = 1;
  setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  address.sin_port = htons(static_cast<uint16_t>(port));
  if (server < 0 || bind(server, reinterpret_cast<sockaddr *>(&address), sizeof(address)) != 0 ||
      listen(server, 2) != 0) {
    std::perror("local-tts: listen");
    SherpaOnnxDestroyOfflineTts(tts);
    return 3;
  }
  std::fprintf(stderr, "local-tts: ready port=%d sample_rate=%d\n", port, sample_rate);

  while (running) {
    const int client = accept(server, nullptr, nullptr);
    if (client < 0) continue;
    HandleClient(client, tts, sample_rate);
    close(client);
  }
  close(server);
  SherpaOnnxDestroyOfflineTts(tts);
  return 0;
}
