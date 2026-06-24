# Jarvis-Portable

Conversational AI assistant with voice control, barge-in, computer vision, persistent memory, plugin system, and self-improvement.

## Overview

Conversational AI assistant with voice control, barge-in, computer vision, persistent memory, plugin system, and self-improvement.

## Features

- Voice-controlled interaction with wake word detection and barge-in support
- Computer vision via OpenRouter multimodal LLM (camera capture, screen analysis)
- Persistent semantic memory (facts, preferences, conversation history)
- Plugin system for extending capabilities (weather, wiki, automation, brain bridge)
- Self-improvement pipeline that analyzes failures and generates patches
- Web UI with WebSocket communication and token authentication
- TTS with configurable voice, caching, and interruptible playback
- Multi-provider LLM support (OpenRouter, OpenAI, Anthropic, Gemini)
- Reminder system with persistent storage
- GitHub integration for status, push, pull, repo management

## Installation

### Prerequisites

- Python
- Git

### Steps

```
git clone https://github.com/judeako402-dotcom/Jarvis-Portable.git
cd Jarvis-Portable
pip install -r requirements.txt
download Vosk model from https://alphacephei.com/vosk/models
cp .env.example .env  # configure API keys
```

## Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| OPENROUTER_API_KEY | API key for LLM provider | Required |
| GITHUB_TOKEN | GitHub personal access token | Optional |
| JARVIS_WEB_TOKEN | Auth token for web UI | Optional |
| JARVIS_WEB_HOST | Web UI bind address | 127.0.0.1 |

## Usage

See the project documentation for detailed usage instructions.

## Use Cases

- Hands-free desktop assistant for development workflow (git, file operations, reminders)
- Voice-controlled smart home hub when paired with Home Assistant
- AI-powered note-taking and memory aid with persistent fact storage
- Extensible automation platform through custom plugins

## License

MIT