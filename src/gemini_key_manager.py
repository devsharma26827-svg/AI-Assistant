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

    def get_current_key(self) -> str:
        return self.api_keys[self.current_index]
        
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
            
        time.sleep(2)
        total_keys = len(self.api_keys)
        attempts = 0
        max_total_attempts = total_keys * (max_retries_per_key + 1)
        
        while attempts < max_total_attempts:
            current_key = self.get_current_key()
            
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
                    
                    if is_rate_limit and total_keys > 1:
                        logger.warning(f"Rate limit hit on key {current_key[-4:]}: {e}. Rotating keys...")
                        self._rotate_key()
                        attempts += 1
                        time.sleep(1)
                        break # Break inner model loop to restart outer key loop with new key
                    
                    # 3. Hard Errors
                    logger.error(f"API Error (Not rate limit/model): {e}")
                    raise e
                    
        raise Exception("All API keys and models exhausted or max retries reached.")

# Global instance for easy importing
gemini_key_manager = GeminiKeyManager()
