"""FinTalk Voice Agent — Self-Hosted Local WebRTC/WebSocket Voice Pipeline (Phase 2).

100% Free & Self-Hosted:
- Replaces third-party room services with a direct local WebSocket audio stream.
- Embedded dark-mode web client served at http://127.0.0.1:8765.
- Speech-to-Text: Deepgram STT
- LLM Reasoning: OpenAI GPT-4o
- Text-to-Speech: Cartesia TTS (16kHz PCM)
- Interruption: Silero VAD
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from loguru import logger
import uvicorn

load_dotenv(override=True)

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame, TextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

app = FastAPI(title="FinTalk Local Voice Assistant")


class RawAudioSerializer(FrameSerializer):
    """Serializes and deserializes raw 16kHz PCM audio bytes."""

    async def serialize(self, frame: Frame) -> bytes | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes):
            return InputAudioRawFrame(audio=data, sample_rate=16000, num_channels=1)
        return None


# HTML Web Client interface with Web Audio API capture and playback
HTML_CLIENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FinTalk — AI Banking Voice Assistant</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-card: rgba(18, 24, 38, 0.75);
            --border-glass: rgba(255, 255, 255, 0.08);
            --accent-blue: #38bdf8;
            --accent-green: #10b981;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Plus Jakarta Sans', sans-serif;
        }

        body {
            background: radial-gradient(circle at 50% 10%, #172554, var(--bg-primary) 65%);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }

        .container {
            width: 100%;
            max-width: 520px;
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border: 1px solid var(--border-glass);
            border-radius: 28px;
            padding: 40px 32px;
            text-align: center;
            box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.7);
        }

        .brand-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            background: rgba(56, 189, 248, 0.1);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 999px;
            color: var(--accent-blue);
            font-size: 0.85rem;
            font-weight: 600;
            margin-bottom: 20px;
        }

        h1 {
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 8px;
        }

        p.subtitle {
            color: var(--text-secondary);
            font-size: 0.95rem;
            margin-bottom: 36px;
        }

        .avatar-wrap {
            position: relative;
            width: 150px;
            height: 150px;
            margin: 0 auto 36px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .pulse-ring {
            position: absolute;
            inset: 0;
            border-radius: 50%;
            border: 2px solid var(--accent-blue);
            opacity: 0;
            transform: scale(0.85);
            transition: all 0.3s ease;
        }

        .pulse-ring.active {
            animation: pulse-wave 2s infinite cubic-bezier(0.4, 0, 0.6, 1);
        }

        @keyframes pulse-wave {
            0% { transform: scale(0.85); opacity: 0.8; }
            50% { opacity: 0.3; }
            100% { transform: scale(1.35); opacity: 0; }
        }

        .mic-button {
            position: relative;
            width: 100px;
            height: 100px;
            border-radius: 50%;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            border: none;
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2.2rem;
            cursor: pointer;
            box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.5);
            transition: all 0.2s ease;
            z-index: 2;
        }

        .mic-button:hover {
            transform: scale(1.05);
            box-shadow: 0 15px 35px -5px rgba(37, 99, 235, 0.7);
        }

        .mic-button.active {
            background: linear-gradient(135deg, #ef4444, #dc2626);
            box-shadow: 0 10px 25px -5px rgba(239, 68, 68, 0.5);
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 18px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-glass);
            border-radius: 12px;
            font-size: 0.9rem;
            color: var(--text-secondary);
            margin-bottom: 24px;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #64748b;
        }

        .status-dot.connected {
            background: var(--accent-green);
            box-shadow: 0 0 12px var(--accent-green);
        }

        .status-dot.talking {
            background: var(--accent-blue);
            box-shadow: 0 0 12px var(--accent-blue);
        }

        .call-hint {
            font-size: 0.82rem;
            color: var(--text-secondary);
            line-height: 1.5;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="brand-badge">⚡ FinTalk Voice Agent (Local WebRTC/WS)</div>
        <h1>FinTalk Assistant</h1>
        <p class="subtitle">Speak naturally with your AI banking assistant.</p>

        <div class="avatar-wrap">
            <div id="pulseRing" class="pulse-ring"></div>
            <button id="callBtn" class="mic-button" onclick="toggleCall()">🎙️</button>
        </div>

        <div class="status-pill">
            <div id="statusDot" class="status-dot"></div>
            <span id="statusText">Ready to connect</span>
        </div>

        <p class="call-hint">
            Click the microphone to start talking. Speak into your mic and listen through your speakers.
        </p>
    </div>

    <script>
        let ws = null;
        let audioContext = null;
        let playContext = null;
        let mediaStream = null;
        let scriptNode = null;
        let isConnected = false;
        let nextPlayTime = 0;

        const callBtn = document.getElementById("callBtn");
        const pulseRing = document.getElementById("pulseRing");
        const statusDot = document.getElementById("statusDot");
        const statusText = document.getElementById("statusText");

        async function toggleCall() {
            if (isConnected) {
                endCall();
            } else {
                await startCall();
            }
        }

        async function startCall() {
            try {
                statusText.innerText = "Connecting...";
                playContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
                if (playContext.state === "suspended") {
                    await playContext.resume();
                }

                // Connect to local WebSocket endpoint
                const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
                ws = new WebSocket(`${wsProto}//${window.location.host}/ws`);
                ws.binaryType = "arraybuffer";

                ws.onopen = async () => {
                    isConnected = true;
                    callBtn.classList.add("active");
                    pulseRing.classList.add("active");
                    statusDot.className = "status-dot connected";
                    statusText.innerText = "Connected — Listening...";
                    await startAudioCapture();
                };

                ws.onmessage = async (event) => {
                    if (event.data instanceof ArrayBuffer) {
                        playPCM(event.data);
                    }
                };

                ws.onclose = () => {
                    endCall();
                };

                ws.onerror = (e) => {
                    console.error("WebSocket error:", e);
                    endCall();
                };

            } catch (err) {
                console.error("Failed to start voice call:", err);
                statusText.innerText = "Error: " + err.message;
                endCall();
            }
        }

        async function startAudioCapture() {
            mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true }
            });

            audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            const source = audioContext.createMediaStreamSource(mediaStream);
            scriptNode = audioContext.createScriptProcessor(4096, 1, 1);

            scriptNode.onaudioprocess = (e) => {
                if (!isConnected || !ws || ws.readyState !== WebSocket.OPEN) return;
                const inputData = e.inputBuffer.getChannelData(0);
                const pcm16 = convertFloatTo16BitPCM(inputData);
                ws.send(pcm16.buffer);
            };

            source.connect(scriptNode);
            scriptNode.connect(audioContext.destination);
        }

        function playPCM(arrayBuffer) {
            statusDot.className = "status-dot talking";
            statusText.innerText = "FinTalk is speaking...";

            const int16 = new Int16Array(arrayBuffer);
            const float32 = new Float32Array(int16.length);
            for (let i = 0; i < int16.length; i++) {
                float32[i] = int16[i] / 32768.0;
            }

            const audioBuffer = playContext.createBuffer(1, float32.length, 16000);
            audioBuffer.copyToChannel(float32, 0);

            const source = playContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(playContext.destination);

            const now = playContext.currentTime;
            if (nextPlayTime < now) {
                nextPlayTime = now + 0.02;
            }
            source.start(nextPlayTime);
            nextPlayTime += audioBuffer.duration;

            source.onended = () => {
                if (playContext && playContext.currentTime >= nextPlayTime - 0.05) {
                    statusDot.className = "status-dot connected";
                    statusText.innerText = "Connected — Listening...";
                }
            };
        }

        function convertFloatTo16BitPCM(float32Array) {
            const int16 = new Int16Array(float32Array.length);
            for (let i = 0; i < float32Array.length; i++) {
                let s = Math.max(-1, Math.min(1, float32Array[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            return int16;
        }

        function endCall() {
            isConnected = false;
            callBtn.classList.remove("active");
            pulseRing.classList.remove("active");
            statusDot.className = "status-dot";
            statusText.innerText = "Ready to connect";

            if (ws) {
                ws.close();
                ws = null;
            }
            if (mediaStream) {
                mediaStream.getTracks().forEach(t => t.stop());
                mediaStream = null;
            }
            if (scriptNode) {
                scriptNode.disconnect();
                scriptNode = null;
            }
            if (audioContext) {
                audioContext.close();
                audioContext = null;
            }
            if (playContext) {
                playContext.close();
                playContext = null;
            }
            nextPlayTime = 0;
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def serve_client():
    """Serves the FinTalk voice client web page."""
    return HTMLResponse(content=HTML_CLIENT)


@app.websocket("/ws")
async def websocket_voice_endpoint(websocket: WebSocket):
    """Handles the real-time bidirectional audio stream with Pipecat."""
    await websocket.accept()
    logger.info("Browser client connected to voice WebSocket.")

    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    cartesia_key = os.getenv("CARTESIA_API_KEY")

    if not groq_key and not openai_key:
        logger.error("Missing GROQ_API_KEY (or OPENAI_API_KEY) in .env")
        await websocket.close(code=1008, reason="Missing GROQ_API_KEY")
        return

    for key_name, val in [("DEEPGRAM_API_KEY", deepgram_key), ("CARTESIA_API_KEY", cartesia_key)]:
        if not val or val.startswith("your_"):
            logger.error(f"Missing {key_name} in .env")
            await websocket.close(code=1008, reason=f"Missing {key_name}")
            return

    # 1. Initialize WebSocket Transport with Raw Audio Serializer
    ws_params = FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,
        serializer=RawAudioSerializer(),
    )
    transport = FastAPIWebsocketTransport(websocket=websocket, params=ws_params)

    # 2. Voice Activity Detection & Interruption
    vad_processor = VADProcessor(vad_analyzer=SileroVADAnalyzer())

    # 3. Speech-to-Text: Deepgram
    stt = DeepgramSTTService(api_key=deepgram_key.strip())

    # 4. Conversation Context & LLM (Groq Llama 3.3 70B by default, or OpenAI GPT-4o)
    system_instruction = (
        "You are FinTalk, a friendly and professional voice banking assistant. "
        "Keep your responses concise, conversational, and direct, suitable for speech. "
        "Do not use markdown, bullet points, or complex symbols since your answers are spoken aloud. "
        "In this phase, you are demonstrating your conversational voice abilities."
    )
    context = LLMContext()

    if groq_key and not groq_key.startswith("your_"):
        logger.info("Using Groq (openai/gpt-oss-120b) for ultra-fast, free conversational intelligence.")
        llm = GroqLLMService(
            api_key=groq_key.strip(),
            settings=GroqLLMService.Settings(
                model="openai/gpt-oss-120b",
                system_instruction=system_instruction,
            ),
        )
    else:
        logger.info("Using OpenAI (GPT-4o) for conversational intelligence.")
        llm = OpenAILLMService(
            api_key=openai_key.strip(),
            settings=OpenAILLMService.Settings(
                model="gpt-4o",
                system_instruction=system_instruction,
            ),
        )
    aggregator_pair = LLMContextAggregatorPair(context)

    # 5. Text-to-Speech: Cartesia (16kHz PCM linear audio)
    tts = CartesiaTTSService(
        api_key=cartesia_key.strip(),
        sample_rate=16000,
        settings=CartesiaTTSService.Settings(
            voice="79a125e8-cd45-4c13-8a67-188112f4dd22",
        ),
    )

    # 6. Assemble Pipecat Frame Pipeline
    pipeline = Pipeline(
        [
            transport.input(),            # Incoming raw 16kHz PCM audio
            vad_processor,                # Evaluates user voice activity
            stt,                          # Deepgram speech-to-text
            aggregator_pair.user(),       # Aggregates user utterance
            llm,                          # OpenAI GPT-4o response
            tts,                          # Cartesia voice synthesis
            transport.output(),           # Outgoing synthesized audio
            aggregator_pair.assistant(),  # Context assistant message
        ]
    )

    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

    # Send initial spoken greeting
    await task.queue_frames([TextFrame("Hello! I am FinTalk, your AI banking assistant. How can I help you today?")])

    # Run the pipeline
    runner = PipelineRunner()
    try:
        await runner.run(task)
    except WebSocketDisconnect:
        logger.info("Browser client disconnected.")
    except Exception as e:
        logger.error(f"Error in voice pipeline: {e}")


def main():
    """Start the FinTalk voice assistant server."""
    print("\n" + "=" * 65)
    print("🎤 FinTalk Voice Assistant (100% Free Self-Hosted Mode)")
    print("👉 Open your browser at:")
    print("   http://127.0.0.1:8765")
    print("=" * 65 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
