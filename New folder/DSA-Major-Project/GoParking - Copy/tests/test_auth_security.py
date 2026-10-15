import unittest

from auth_security import hash_password, is_valid_email, verify_password


class PasswordHashTests(unittest.TestCase):
    def test_hash_is_salted_and_verifies(self):
        first = hash_password("a-long-example-password")
        second = hash_password("a-long-example-password")

        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("a-long-example-password", first))
        self.assertFalse(verify_password("incorrect-password", first))
        self.assertNotIn("a-long-example-password", first)

    def test_malformed_hash_is_rejected(self):
        self.assertFalse(verify_password("password", "invalid"))


class EmailValidationTests(unittest.TestCase):
    def test_accepts_normalized_email_shapes(self):
        self.assertTrue(is_valid_email("student@example.edu"))
        self.assertTrue(is_valid_email(" student@example.edu "))

    def test_rejects_incomplete_email_shapes(self):
        for email in ("", "student", "student@", "@example.edu", "a b@example.edu"):
            with self.subTest(email=email):
                self.assertFalse(is_valid_email(email))


if __name__ == "__main__":
    unittest.main()
