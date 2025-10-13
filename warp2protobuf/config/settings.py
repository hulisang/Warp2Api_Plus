#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration settings for Warp API server

Contains environment variables, paths, and constants.
"""
import os
import pathlib
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Path configurations
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
PROTO_DIR = SCRIPT_DIR / "proto"
LOGS_DIR = SCRIPT_DIR / "logs"

# API configuration
WARP_URL = "https://app.warp.dev/ai/multi-agent"

# Environment variables with defaults
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8002"))
WARP_JWT = os.getenv("WARP_JWT")

# Client headers configuration
CLIENT_VERSION = "v0.2025.08.06.08.12.stable_02"
OS_CATEGORY = "Windows"
OS_NAME = "Windows"
OS_VERSION = "11 (26100)"

# Protobuf field names for text detection
TEXT_FIELD_NAMES = ("text", "prompt", "query", "content", "message", "input")
PATH_HINT_BONUS = ("conversation", "query", "input", "user", "request", "delta")

# Response parsing configuration
SYSTEM_STR = {"agent_output.text", "server_message_data", "USER_INITIATED", "agent_output", "text"}

# JWT refresh configuration
REFRESH_TOKEN_B64 = "Z3JhbnRfdHlwZT1yZWZyZXNoX3Rva2VuJnJlZnJlc2hfdG9rZW49QU1mLXZCeFNSbWRodmVHR0JZTTY5cDA1a0RoSW4xaTd3c2NBTEVtQzlmWURScEh6akVSOWRMN2trLWtIUFl3dlk5Uk9rbXk1MHFHVGNJaUpaNEFtODZoUFhrcFZQTDkwSEptQWY1Zlo3UGVqeXBkYmNLNHdzbzhLZjNheGlTV3RJUk9oT2NuOU56R2FTdmw3V3FSTU5PcEhHZ0JyWW40SThrclc1N1I4X3dzOHU3WGNTdzh1MERpTDlIcnBNbTBMdHdzQ2g4MWtfNmJiMkNXT0ViMWxJeDNIV1NCVGVQRldzUQ=="
REFRESH_URL = "https://app.warp.dev/proxy/token?key=AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs" 