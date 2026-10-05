import os
import tempfile
import unittest
from unittest.mock import patch


_TEST_DATABASE_DIR = tempfile.TemporaryDirectory(prefix="english-bot-tests-")
_TEST_ENV = {
    "BOT_TOKEN": "123456789:TEST_TOKEN_FOR_UNIT_TESTS",
    "ADMIN_ID": "1",
    "DB_NAME": os.path.join(_TEST_DATABASE_DIR.name, "imported-bot.db"),
    "NOVA_API_KEY": "",
    "GEMINI_API_KEY": "",
}

with patch.dict(os.environ, _TEST_ENV):
    import bot


def make_question(sentence):
    return {
        "level": "beginner",
        "topic": "🟢 Present Simple",
        "sentence": sentence,
        "translation": "Tarjima",
        "correct_answer": "works",
        "option1": "works",
        "option2": "work",
        "option3": "working",
        "explanation": "Izoh",
        "difficulty": "medium",
        "source": "test",
    }


class SplitMessageTests(unittest.TestCase):
    def test_splitting_preserves_all_text_and_respects_limit(self):
        text = "Alpha sentence with spaces.\n" * 400

        chunks = bot.split_message(text, limit=80)

        self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_splitting_long_unbroken_text_preserves_all_text(self):
        text = "x" * 250

        chunks = bot.split_message(text, limit=80)

        self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_non_positive_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            bot.split_message("text", limit=0)


class DatabaseQuestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="english-bot-db-test-")
        self.db = bot.Database(os.path.join(self.temp_dir.name, "test.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bulk_insert_unique_ignores_normalized_duplicates(self):
        question_ids = self.db.bulk_insert_unique([
            make_question("She works at the library."),
            make_question("SHE works at the library!"),
            make_question("   "),
        ])

        self.assertEqual(len(question_ids), 1)
        self.assertEqual(self.db.count_questions(), 1)

    def test_daily_plan_does_not_serve_the_same_wrong_question_twice(self):
        question_ids = self.db.bulk_insert_unique([
            make_question("Nodira checks the schedule every morning."),
            make_question("The students review their notes after class."),
            make_question("Our neighbour waters the garden on Fridays."),
        ])
        for question_id in question_ids[:2]:
            self.db.record_answer(
                telegram_id=42,
                question_id=question_id,
                topic="🟢 Present Simple",
                answer="incorrect",
                correct=False,
                xp=0,
            )

        first = self.db.plan_questions(
            42, "🟢 Present Simple", "beginner", limit=1
        )
        second = self.db.plan_questions(
            42, "🟢 Present Simple", "beginner", limit=1
        )

        self.assertEqual([question["id"] for question in first], [question_ids[1]])
        self.assertEqual([question["id"] for question in second], [question_ids[0]])


if __name__ == "__main__":
    unittest.main()
