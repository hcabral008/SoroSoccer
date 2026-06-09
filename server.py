#!/usr/bin/env python3
"""
SoroSoccer — Backend WebSocket para compilação e execução C++ em tempo real.

Protocolo:
  Browser → Server (JSON):
    { "type": "compile", "code": "...", "robotIdx": 0 }
    { "type": "sensor_response", "value": 42 }   ← resposta a pedido de sensor
    { "type": "delay_ack" }                        ← browser confirma que delay passou
    { "type": "stop" }

  Server → Browser (JSON):
    { "type": "compiled" }                         ← compilação OK
    { "type": "compile_error", "message": "..." }
    { "type": "cmd", "cmd": "move", "m": "front", "f": 0.8 }
    { "type": "cmd", "cmd": "dribbler", "on": true }
    { "type": "cmd", "cmd": "kick" }
    { "type": "cmd", "cmd": "serial", "msg": "...", "nl": true }
    { "type": "cmd", "cmd": "sensor", "sensor": "gyro" }   ← precisa de resposta
    { "type": "cmd", "cmd": "sensor", "sensor": "line", "dir": 0 }
    { "type": "cmd", "cmd": "sensor", "sensor": "ir_ball" } ← retorna dir*1000+intensity
    { "type": "cmd", "cmd": "delay", "ms": 500 }            ← precisa de delay_ack
    { "type": "cmd", "cmd": "done" }
    { "type": "log", "level": "info|ok|err|warn", "message": "..." }

Uso:
  pip install websockets
  python3 server.py
  # depois abra index.html no browser
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading

# ── tenta importar websockets ────────────────────────────────────────────────
try:
    import websockets
    from websockets.server import serve
except ImportError:
    print("Erro: instale websockets com:  pip install websockets")
    sys.exit(1)

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8765))

# ─────────────────────────────────────────────────────────────────────────────
# Header C++ injetado antes do código do usuário.
# O binário se comunica com o backend via stdin/stdout usando o protocolo
# __CMD__{JSON}\n  (output do C++)
# linha de resposta  (input para o C++, quando necessário)
# ─────────────────────────────────────────────────────────────────────────────
ARDUINO_HEADER = r"""
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <string>
#include <stdint.h>

// ── Tipos Arduino ────────────────────────────────────────────────────────────
typedef unsigned char  uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int   uint32_t;
typedef signed char    int8_t;
typedef short          int16_t;
typedef int            int32_t;
typedef unsigned char  byte;
typedef bool           boolean;

#define HIGH 1
#define LOW  0
#define INPUT    0
#define OUTPUT   1
#define INPUT_PULLUP 2
#undef PI
#define PI 3.14159265358979323846f

// Sensores de linha
#define SENSOR_FRONT 0
#define SENSOR_RIGHT 1
#define SENSOR_BACK  2
#define SENSOR_LEFT  3

// ── Tempo simulado ───────────────────────────────────────────────────────────
static long long _sim_time_ms = 0;

// ── Emite comando e lê ack/valor do stdin (protocolo bidirecional) ───────────
static inline void _emit(const char* json_str) {
    fputs("__CMD__", stdout);
    fputs(json_str, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

// Emite e aguarda uma linha de resposta; retorna o valor inteiro
static int _emit_wait_int(const char* json_str) {
    _emit(json_str);
    char buf[64] = {0};
    if (fgets(buf, sizeof(buf), stdin)) {
        return atoi(buf);
    }
    return 0;
}

// Emite e aguarda ack (qualquer linha)
static void _emit_wait_ack(const char* json_str) {
    _emit(json_str);
    char buf[16] = {0};
    (void)fgets(buf, sizeof(buf), stdin);
}

// ── Movimentação ─────────────────────────────────────────────────────────────
void moveFront(float f=1.0f)   { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"front\",\"f\":%.3f}",f); _emit(b); }
void moveBack(float f=1.0f)    { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"back\",\"f\":%.3f}",f);  _emit(b); }
void moveLeft(float f=1.0f)    { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"left\",\"f\":%.3f}",f);  _emit(b); }
void moveRight(float f=1.0f)   { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"right\",\"f\":%.3f}",f); _emit(b); }
void moveUR(float f=1.0f)      { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"ur\",\"f\":%.3f}",f);    _emit(b); }
void moveUL(float f=1.0f)      { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"ul\",\"f\":%.3f}",f);    _emit(b); }
void moveDR(float f=1.0f)      { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"dr\",\"f\":%.3f}",f);    _emit(b); }
void moveDL(float f=1.0f)      { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"dl\",\"f\":%.3f}",f);    _emit(b); }
void rotateLeft(float f=1.0f)  { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"rotl\",\"f\":%.3f}",f);  _emit(b); }
void rotateRight(float f=1.0f) { char b[80]; snprintf(b,80,"{\"cmd\":\"move\",\"m\":\"rotr\",\"f\":%.3f}",f);  _emit(b); }
void stop(float f=1.0f)        { _emit("{\"cmd\":\"move\",\"m\":\"stop\",\"f\":1.0}"); }

// ── Dribbler / Kicker ────────────────────────────────────────────────────────
void startDribbler() { _emit("{\"cmd\":\"dribbler\",\"on\":true}");  }
void stopDribbler()  { _emit("{\"cmd\":\"dribbler\",\"on\":false}"); }
void pulseKicker()   { _emit("{\"cmd\":\"kick\"}"); }

// ── Tempo ────────────────────────────────────────────────────────────────────
// delay() bloqueia o processo e aguarda o simulador confirmar que o tempo passou.
// Isso garante que o C++ só continua depois que a física rodou aquele intervalo.
void delay(long ms) {
    if (ms <= 0) return;
    char b[80];
    snprintf(b, 80, "{\"cmd\":\"delay\",\"ms\":%ld}", ms);
    _emit_wait_ack(b);
    _sim_time_ms += ms;
}

long millis() { return (long)_sim_time_ms; }
long micros() { return (long)(_sim_time_ms * 1000LL); }

// ── Sensores (bloqueantes — retornam valor real da simulação) ────────────────
int getGyro() {
    return _emit_wait_int("{\"cmd\":\"sensor\",\"sensor\":\"gyro\"}");
}

int getLineSensor(int dir) {
    char b[80];
    snprintf(b, 80, "{\"cmd\":\"sensor\",\"sensor\":\"line\",\"dir\":%d}", dir);
    return _emit_wait_int(b);
}

int readLine(int dir=-1) {
    if (dir < 0) {
        // qualquer sensor
        char b[80];
        snprintf(b, 80, "{\"cmd\":\"sensor\",\"sensor\":\"line_any\"}");
        return _emit_wait_int(b);
    }
    return getLineSensor(dir);
}

// ── Sensor IR da Bola ────────────────────────────────────────────
// Retorna um inteiro codificado: dir * 1000 + intensity
//   dir: 5=frente/dribbler, 1-4=esquerda, 6-9=direita, 0=atrás/oculta
//   intensity: 0..150 (150 = bola encostada no robô)
// Use getBallDirection() e getBallIntensity() para decodificar.
int _getBallIRRaw() {
    return _emit_wait_int("{\"cmd\":\"sensor\",\"sensor\":\"ir_ball\"}");
}

// Retorna apenas a direção da bola (0-9)
int getBallDirection() {
    int raw = _getBallIRRaw();
    return raw / 1000;
}

// Retorna apenas a intensidade (0-150)
int getBallIntensity() {
    int raw = _getBallIRRaw();
    return raw % 1000;
}

// ── Sensores de Distância ────────────────────────────────────────
// Retorna a distância em centímetros na lateral indicada.
// O sensor detecta paredes, gols e outros robôs.
static int _getDistRaw(const char* side) {
    char b[128];
    snprintf(b, 128, "{\"cmd\":\"sensor\",\"sensor\":\"dist_%s\"}", side);
    return _emit_wait_int(b);
}
int getDistanceFront() { return _getDistRaw("front"); }
int getDistanceBack()  { return _getDistRaw("back");  }
int getDistanceLeft()  { return _getDistRaw("left");  }
int getDistanceRight() { return _getDistRaw("right"); }

// ── Funções Arduino padrão (no-ops) ─────────────────────────────────────────
void pinMode(int, int) {}
void digitalWrite(int, int) {}
int  digitalRead(int) { return 0; }
void analogWrite(int, int) {}
int  analogRead(int) { return 0; }
void noInterrupts() {}
void interrupts() {}

// ── Matemática ───────────────────────────────────────────────────────────────
using std::abs; using std::min; using std::max;
using std::sqrt; using std::pow; using std::sin; using std::cos; using std::tan;
using std::atan2; using std::asin; using std::acos;

float constrain_f(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }
#define constrain(x,lo,hi) constrain_f((float)(x),(float)(lo),(float)(hi))
#define map(x,il,ih,ol,oh) (((float)(x)-(il))*((float)(oh)-(ol))/((float)(ih)-(il))+(ol))
#define random(a,...) (rand() % (int)(a))

// ── Serial ───────────────────────────────────────────────────────────────────
struct _Serial_t {
    void begin(long) {}

    void _send(const char* msg, bool nl) {
        // Escapa aspas e barras para JSON
        char out[1024];
        char esc[512];
        int j = 0;
        for (int i = 0; msg[i] && j < 510; i++) {
            if (msg[i] == '"' || msg[i] == '\\') esc[j++] = '\\';
            esc[j++] = msg[i];
        }
        esc[j] = 0;
        snprintf(out, sizeof(out),
            "{\"cmd\":\"serial\",\"msg\":\"%s\",\"nl\":%s}",
            esc, nl ? "true" : "false");
        _emit(out);
    }

    void print(const char* s) { _send(s, false); }
    void println(const char* s) { _send(s, true); }
    void println() { _send("", true); }

    void print(int v)    { char b[32]; snprintf(b,32,"%d",v);   _send(b, false); }
    void println(int v)  { char b[32]; snprintf(b,32,"%d",v);   _send(b, true);  }
    void print(long v)   { char b[32]; snprintf(b,32,"%ld",v);  _send(b, false); }
    void println(long v) { char b[32]; snprintf(b,32,"%ld",v);  _send(b, true);  }
    void print(float v)  { char b[32]; snprintf(b,32,"%.4g",v); _send(b, false); }
    void println(float v){ char b[32]; snprintf(b,32,"%.4g",v); _send(b, true);  }
    void print(double v) { char b[32]; snprintf(b,32,"%.6g",v); _send(b, false); }
    void println(double v){char b[32]; snprintf(b,32,"%.6g",v); _send(b, true);  }
    void print(bool v)   { _send(v ? "1" : "0", false); }
    void println(bool v) { _send(v ? "1" : "0", true);  }
} Serial;

// ── Proteção contra loop infinito sem delay ──────────────────────────────────
// Conta iterações de loop(). Sem nenhum delay() em 100k iterações,
// o programa provavelmente travou — encerramos.
static int _iter_count = 0;
static const int _MAX_ITER = 1000000;

// ── Declarações forward ──────────────────────────────────────────────────────
void setup();
void loop();

int main() {
    setup();
    while (_iter_count++ < _MAX_ITER) {
        loop();
    }
    _emit("{\"cmd\":\"done\"}");
    return 0;
}

// ── Código do usuário abaixo ─────────────────────────────────────────────────
"""

# ─────────────────────────────────────────────────────────────────────────────
# Estado de execução por WebSocket (uma conexão = um robô rodando)
# ─────────────────────────────────────────────────────────────────────────────
class RobotSession:
    def __init__(self, ws):
        self.ws = ws
        self.proc = None          # subprocess do binário C++
        self.stopped = False
        self.sensor_future = None # asyncio.Future esperando resposta de sensor
        self.delay_future  = None # asyncio.Future esperando delay_ack
        self._reader_task  = None

    async def send(self, obj):
        try:
            await self.ws.send(json.dumps(obj))
        except Exception:
            pass

    async def log(self, level, msg):
        await self.send({"type": "log", "level": level, "message": msg})

    def kill(self):
        self.stopped = True
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass
        if self.sensor_future and not self.sensor_future.done():
            self.sensor_future.cancel()
        if self.delay_future and not self.delay_future.done():
            self.delay_future.cancel()
        if self._reader_task:
            self._reader_task.cancel()


# ─────────────────────────────────────────────────────────────────────────────
# Compila código C++ e retorna (ok: bool, message: str, binary_path: str|None)
# ─────────────────────────────────────────────────────────────────────────────
def compile_cpp(user_code: str):
    full_code = ARDUINO_HEADER + "\n" + user_code

    src_fd, src_path = tempfile.mkstemp(suffix=".cpp")
    bin_fd, bin_path = tempfile.mkstemp(suffix=".bin")
    os.close(src_fd)
    os.close(bin_fd)

    with open(src_path, "w") as f:
        f.write(full_code)

    header_lines = ARDUINO_HEADER.count("\n") + 1

    result = subprocess.run(
        ["g++", "-std=c++17", "-O1", "-Wall", "-Wno-unused-result",
         "-o", bin_path, src_path],
        capture_output=True, text=True, timeout=15
    )

    os.unlink(src_path)

    if result.returncode != 0:
        # Ajusta números de linha (remove offset do header)
        raw = result.stderr or result.stdout
        lines = []
        for ln in raw.splitlines():
            import re
            def shift(m):
                n = int(m.group(1)) - header_lines
                return f"linha {max(1, n)}" if n > 0 else ""
            adj = re.sub(r"<stdin>:(\d+)", shift, ln)
            if adj.strip():
                lines.append(adj.strip())
        os.unlink(bin_path)
        return False, "\n".join(lines), None

    os.chmod(bin_path, 0o755)
    return True, "", bin_path


# ─────────────────────────────────────────────────────────────────────────────
# Lê linhas do stdout do processo C++ e despacha para o browser ou para futures
# ─────────────────────────────────────────────────────────────────────────────
async def _process_reader(session: RobotSession, loop: asyncio.AbstractEventLoop):
    proc = session.proc
    try:
        while not session.stopped:
            # Leitura bloqueante em thread separada para não travar o event loop
            line = await loop.run_in_executor(None, proc.stdout.readline)
            if not line:
                break
            line = line.strip()
            if not line.startswith("__CMD__"):
                continue

            try:
                cmd = json.loads(line[7:])
            except json.JSONDecodeError:
                continue

            if session.stopped:
                break

            cmd_type = cmd.get("cmd", "")

            # ── Comandos de movimento / dribbler / kick / serial ───────────
            if cmd_type in ("move", "dribbler", "kick", "serial", "done"):
                await session.send({"type": "cmd", **cmd})
                if cmd_type == "done":
                    break

            # ── Sensor — precisa de resposta do browser ────────────────────
            elif cmd_type == "sensor":
                fut = loop.create_future()
                session.sensor_future = fut
                await session.send({"type": "cmd", **cmd})
                try:
                    value = await asyncio.wait_for(fut, timeout=5.0)
                except asyncio.TimeoutError:
                    value = 0
                # Responde ao processo C++ via stdin
                await loop.run_in_executor(
                    None,
                    lambda v=value: (proc.stdin.write(f"{v}\n"), proc.stdin.flush())
                )

            # ── Delay — aguarda o browser confirmar que o tempo passou ──────
            elif cmd_type == "delay":
                fut = loop.create_future()
                session.delay_future = fut
                await session.send({"type": "cmd", **cmd})
                try:
                    await asyncio.wait_for(fut, timeout=60.0)
                except asyncio.TimeoutError:
                    pass
                # Manda ack para o C++ continuar
                await loop.run_in_executor(
                    None,
                    lambda: (proc.stdin.write("ok\n"), proc.stdin.flush())
                )

    except Exception as e:
        if not session.stopped:
            await session.log("err", f"Erro interno do runner: {e}")
    finally:
        if not session.stopped:
            await session.send({"type": "cmd", "cmd": "done"})


# ─────────────────────────────────────────────────────────────────────────────
# Handler principal de WebSocket
# ─────────────────────────────────────────────────────────────────────────────
async def handler(websocket):
    session = RobotSession(websocket)
    loop = asyncio.get_event_loop()
    bin_path = None

    await session.log("ok", "Conectado ao backend SoroSoccer. Pronto para compilar.")

    try:
        async for raw in websocket:
            msg = json.loads(raw)
            mtype = msg.get("type", "")

            # ── Compilar + iniciar execução ───────────────────────────────
            if mtype == "compile":
                # Para execução anterior se houver
                session.kill()
                session.stopped = False
                session.sensor_future = None
                session.delay_future  = None

                code      = msg.get("code", "")
                robot_idx = msg.get("robotIdx", 0)

                await session.log("info", "Compilando com GCC C++17...")

                # Compilação em thread (bloqueante)
                ok, err_msg, bin_path = await loop.run_in_executor(
                    None, compile_cpp, code
                )

                if not ok:
                    for ln in err_msg.splitlines():
                        if ln.strip():
                            is_err = "error:" in ln.lower()
                            await session.log("err" if is_err else "warn", ln)
                    await session.send({"type": "compile_error", "message": err_msg})
                    continue

                await session.log("ok", "Compilado! Iniciando execução ao vivo...")
                await session.send({"type": "compiled", "robotIdx": robot_idx})

                # Inicia o processo
                session.proc = subprocess.Popen(
                    [bin_path],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,   # line-buffered
                )

                # Reader roda como task assíncrona
                session._reader_task = asyncio.create_task(
                    _process_reader(session, loop)
                )

            # ── Resposta de sensor (browser → backend → processo C++) ─────
            elif mtype == "sensor_response":
                if session.sensor_future and not session.sensor_future.done():
                    session.sensor_future.set_result(msg.get("value", 0))

            # ── Ack de delay (browser → backend → processo C++) ──────────
            elif mtype == "delay_ack":
                if session.delay_future and not session.delay_future.done():
                    session.delay_future.set_result(True)

            # ── Parar ────────────────────────────────────────────────────
            elif mtype == "stop":
                session.kill()
                await session.log("warn", "Execução interrompida.")

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        session.kill()
        if bin_path and os.path.exists(bin_path):
            try:
                os.unlink(bin_path)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
async def main():
    print(f"SoroSoccer Backend — ws://{HOST}:{PORT}")
    print("Pressione Ctrl+C para parar.\n")
    async with serve(handler, HOST, PORT):
        await asyncio.get_event_loop().create_future()  # roda para sempre

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServidor encerrado.")