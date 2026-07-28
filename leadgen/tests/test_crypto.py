"""Round-trip tests for the shared Fernet secret helper (nexora/crypto.py),
used by leadgen.LeadBuyer.set_api_key/get_api_key for the buyer's API key
at rest."""
from nexora.crypto import decrypt_secret, encrypt_secret


class TestSecretRoundTrip:
    def test_encrypt_then_decrypt_returns_original(self):
        raw = '41bf25b723a34cd38ad16b9de5778722'
        encrypted = encrypt_secret(raw)
        assert encrypted != raw
        assert decrypt_secret(encrypted) == raw

    def test_encrypted_value_is_not_plaintext_substring(self):
        raw = 'super-secret-api-key'
        encrypted = encrypt_secret(raw)
        assert raw not in encrypted

    def test_empty_string_is_empty_safe(self):
        assert encrypt_secret('') == ''
        assert decrypt_secret('') == ''

    def test_decrypt_garbage_returns_empty_not_raise(self):
        assert decrypt_secret('not-a-valid-fernet-token') == ''

    def test_two_encryptions_of_same_value_differ(self):
        """Fernet includes a random IV/timestamp — ciphertext shouldn't be
        deterministic even for the same plaintext."""
        raw = 'same-value'
        assert encrypt_secret(raw) != encrypt_secret(raw)
