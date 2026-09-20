"""
Gemini Key Manager.
Rotates and manages multiple Gemini API keys to prevent rate limits (429) 
and handles automatic model fallbacks across active key configurations.
"""
import os
import time
import logging
from dotenv import load_dotenv

logger = logging.getLogger("gemini_key_manager")
logger.setLevel(logging.INFO)

class GeminiKeyManager:
    def __init__(self):
        load_dotenv(".env")
        load_dotenv(".env.local")
        
        # Parse multiple keys based on comma separated string or multiple keys ending with number
        self.api_keys = []
        
        env_keys = os.getenv("GEMINI_API_KEYS", "")
        if env_keys:
            self.api_keys = [k.strip() for k in env_keys.split(",") if k.strip()]
            
        if not self.api_keys:
            # Fallback to legacy single key or pattern
            single = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if single:
                self.api_keys.append(single)
                
        # Optional: Parse GEMINI_API_KEY_1, GEMINI_API_KEY_2 etc.
        i = 1
        while True:
            key = os.getenv(f"GEMINI_API_KEY_{i}")
            if key and key not in self.api_keys:
                self.api_keys.append(key)
            elif not key and i > 5: # check up to 5
                break
            i += 1
            
        if not self.api_keys:
            logger.warning("No Gemini API keys found in environment!")
            # Still append an empty string so rotation logic doesn't crash, it will just fail at API level
            self.api_keys = [""]
            
        self.current_index = 0
        # key -> unix timestamp until which that key should be skipped because
        # it recently returned a 429/quota error.
        self._key_cooldowns = {}

    def get_current_key(self) -> str:
        return self.api_keys[self.current_index]

    def _all_keys_cooling_down(self, now: float) -> bool:
        if not self._key_cooldowns:
            return False
        return all(self._key_cooldowns.get(k, 0) > now for k in self.api_keys)

    @staticmethod
    def _parse_retry_delay(error_text: str, default: float = 30.0) -> float:
        """Pulls Google's suggested retry delay out of a 429 message."""
        import re
        m = re.search(r"retry in ([\d.]+)s", error_text, re.IGNORECASE)
        if m:
            try:
                return min(300.0, max(5.0, float(m.group(1))))
            except ValueError:
                pass
        m = re.search(r"seconds:\s*(\d+)", error_text)
        if m:
            try:
                return min(300.0, max(5.0, float(m.group(1))))
            except ValueError:
                pass
        return default
        
    def _rotate_key(self):
        old_key = self.api_keys[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.api_keys)
        new_key = self.api_keys[self.current_index]
        logger.warning(f"🔄 Rotating Gemini API Key: ...{old_key[-4:]} -> ...{new_key[-4:]}")

    def execute_with_retry(self, action_func, max_retries_per_key=1, fallback_models=None):
        """
        Executes a Gemini API call (action_func) with Key and Model rotation.
        - action_func: A lambda/function that takes (api_key, model_name) returns response.
        - fallback_models: List of model strings (e.g. ['gemini-2.0-flash', 'gemini-1.5-pro']).
        """
        if fallback_models is None:
            fallback_models = [
                "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", 
                "gemini-2.0-flash-lite-001", "gemini-flash-latest", 
                "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"
            ]
            
        total_keys = len(self.api_keys)
        attempts = 0
        max_total_attempts = total_keys * (max_retries_per_key + 1)

        # If every key is already known to be rate-limited, fail fast instead of
        # cycling through them again — retrying a quota-exhausted key burns more
        # quota and produced the long rotation storms seen in testing.
        now = time.time()
        if self._all_keys_cooling_down(now):
            wait_s = int(max(0, min(self._key_cooldowns.values()) - now))
            raise Exception(
                f"All Gemini API keys are rate-limited right now. Try again in ~{wait_s}s."
            )

        while attempts < max_total_attempts:
            current_key = self.get_current_key()

            # Skip a key that recently returned a rate-limit error.
            if self._key_cooldowns.get(current_key, 0) > time.time():
                self._rotate_key()
                attempts += 1
                continue
            
            # Try all models for the given key before rotating the key
            for model_index, model_name in enumerate(fallback_models):
                try:
                    logger.debug(f"Trying API call with key ending in {current_key[-4:]} logic on model {model_name}")
                    return action_func(current_key, model_name)
                    
                except Exception as e:
                    error_msg = str(e).lower()
                    
                    # 1. Check Model unsupported (404, not found, not supported)
                    is_model_error = any(term in error_msg for term in ["404", "not found", "not supported"])
                    if is_model_error:
                        if model_index < len(fallback_models) - 1:
                            logger.warning(f"Model {model_name} unsupported. Falling back to next model...")
                            continue # Try next model
                        else:
                            logger.error(f"All fallback models failed for this key. Last err: {e}")
                            # If all models fail, we shouldn't necessarily rotate key for a model error, but let's break loop to raise
                            raise e

                    # 2. Check Rate Limit / Quota
                    is_rate_limit = any(term in error_msg for term in ["429", "quota", "exhausted", "too many requests", "deadline", "503", "504", "overloaded"])
                    
                    if is_rate_limit:
                        # Park this key for a cooldown window so parallel/later
                        # calls don't immediately hammer it again.
                        self._key_cooldowns[current_key] = time.time() + self._parse_retry_delay(str(e))
                        logger.warning(f"Rate limit hit on key {current_key[-4:]}. Parking it and rotating...")

                        if self._all_keys_cooling_down(time.time()):
                            raise Exception(
                                "All Gemini API keys are rate-limited right now. Try again shortly."
                            )
                        if total_keys > 1:
                            self._rotate_key()
                        attempts += 1
                        break # Break inner model loop to restart outer key loop with new key
                    
                    # 3. Hard Errors
                    logger.error(f"API Error (Not rate limit/model): {e}")
                    raise e
                    
        raise Exception("All API keys and models exhausted or max retries reached.")

# Global instance for easy importing
gemini_key_manager = GeminiKeyManager()
