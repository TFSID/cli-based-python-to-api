import os
import json
from typing import Optional, Dict, Any
from enum import Enum
import requests


class LLMProvider(Enum):
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"


class LLMClient:
    def __init__(
        self,
        provider: LLMProvider = LLMProvider.GEMINI,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        custom_endpoint: Optional[str] = None
    ):
        self.provider = provider
        self.api_key = api_key or self._get_api_key_from_env()
        self.model_name = model_name or self._get_default_model()
        self.custom_endpoint = custom_endpoint
        
        if not self.api_key and provider != LLMProvider.CUSTOM:
            raise ValueError(f"API key required for {provider.value}")
    
    def _get_api_key_from_env(self) -> Optional[str]:
        env_keys = {
            LLMProvider.GEMINI: "GEMINI_API_KEY",
            LLMProvider.OPENAI: "OPENAI_API_KEY",
            LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY"
        }
        env_key = env_keys.get(self.provider)
        return os.getenv(env_key) if env_key else None
    
    def _get_default_model(self) -> str:
        defaults = {
            LLMProvider.GEMINI: "gemini-1.5-pro",
            LLMProvider.OPENAI: "gpt-4",
            LLMProvider.ANTHROPIC: "claude-3-5-sonnet-20241022"
        }
        return defaults.get(self.provider, "default-model")
    
    def generate(self, prompt: str, **kwargs) -> str:
        if self.provider == LLMProvider.GEMINI:
            return self._call_gemini(prompt, **kwargs)
        elif self.provider == LLMProvider.OPENAI:
            return self._call_openai(prompt, **kwargs)
        elif self.provider == LLMProvider.ANTHROPIC:
            return self._call_anthropic(prompt, **kwargs)
        elif self.provider == LLMProvider.CUSTOM:
            return self._call_custom_endpoint(prompt, **kwargs)
        else:
            raise NotImplementedError(f"Provider {self.provider} not implemented")
    
    def _call_gemini(self, prompt: str, **kwargs) -> str:
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }],
            "generationConfig": {
                "temperature": kwargs.get("temperature", 0.2),
                "maxOutputTokens": kwargs.get("max_tokens", 8192),
                "topP": kwargs.get("top_p", 0.95)
            }
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            raise Exception(f"Gemini API error: {response.status_code} - {response.text}")
        
        result = response.json()
        
        if "candidates" in result and len(result["candidates"]) > 0:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            raise Exception("No response from Gemini API")
    
    def _call_openai(self, prompt: str, **kwargs) -> str:
        
        url = "https://api.openai.com/v1/chat/completions"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": kwargs.get("temperature", 0.2),
            "max_tokens": kwargs.get("max_tokens", 4096)
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
        
        result = response.json()
        return result["choices"][0]["message"]["content"]
    
    def _call_anthropic(self, prompt: str, **kwargs) -> str:
        
        url = "https://api.anthropic.com/v1/messages"
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.2)
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            raise Exception(f"Anthropic API error: {response.status_code} - {response.text}")
        
        result = response.json()
        return result["content"][0]["text"]
    
    def _call_custom_endpoint(self, prompt: str, **kwargs) -> str:
        
        if not self.custom_endpoint:
            raise ValueError("Custom endpoint URL not provided")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.api_key:
            headers["accept"] = "application/json"
            headers["x-api-key"] = self.api_key
            headers["Content-Type"] = "application/json"
        
        payload = {
            "prompt": f"{prompt}",
            "model_name": "gemini-2.5-flash-preview-05-20",
            "temperature": 1,
            "top_p": 0.95,
            "max_output_tokens": 65536,
            "system_instruction": "",
            "user_metadata": ""
        }
        
        
        response = requests.post(self.custom_endpoint, headers=headers, json=payload)
        
        if response.status_code != 200:
            raise Exception(f"Custom API error: {response.status_code} - {response.text}")
        
        result = response.json()
        
        if "response" in result:
            return result["response"]
        elif "text" in result:
            return result["text"]
        elif "content" in result:
            return result["content"]
        elif "output_text" in result:
            return result["output_text"]
        else:
            return str(result)