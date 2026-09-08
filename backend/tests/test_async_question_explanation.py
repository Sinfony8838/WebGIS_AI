import threading
import time
import unittest
from unittest.mock import patch


class AsyncQuestionExplanationTest(unittest.TestCase):
    def setUp(self):
        from tests.test_class_question_practice import ClassQuestionPracticeTest
        ClassQuestionPracticeTest.setUp(self)
        self.cw = self.runtime.classroom
        self.cw.launch_session_question(self.session_id, question_id="qb_pop_1", stage_id="s1", delivery="student")

    def wait_finished(self):
        deadline=time.monotonic()+3
        while self.cw._explanation_requests and time.monotonic()<deadline:
            threading.Event().wait(.01)
        self.assertFalse(self.cw._explanation_requests)

    def test_reveal_returns_while_model_waits_and_does_not_duplicate_work(self):
        entered, release=threading.Event(), threading.Event()
        def model(question):
            entered.set(); release.wait(3)
            return {"text":"补充讲解", "generator":"minimax"}
        with patch.object(self.cw.config,"minimax_enabled",return_value=True), patch.object(self.cw,"_compose_ai_explanation",side_effect=model) as compose:
            try:
                started=time.monotonic()
                result=self.cw.reveal_session_question(self.session_id)
                self.assertLess(time.monotonic()-started,1)
                self.assertTrue(entered.wait(1))
                self.assertEqual(result["timer"]["ai_explanation_status"],"pending")
                self.assertEqual(result["official"]["answer"],"气候与地形")
                self.cw.reveal_session_question(self.session_id)
                self.assertEqual(compose.call_count,1)
                self.assertEqual(sum(e["type"]=="question_revealed" for e in self.store.get_class_session(self.session_id).events),1)
            finally:
                release.set(); self.wait_finished()
        result=self.cw.get_question_explanation(self.session_id)
        self.assertEqual(result["timer"]["ai_explanation"]["text"],"补充讲解")
        self.assertEqual(result["timer"]["ai_explanation_status"],"ready")

    def test_late_answer_does_not_overwrite_same_question_relaunched(self):
        entered, release=threading.Event(), threading.Event()
        def model(question):
            entered.set(); release.wait(3)
            return {"text":"旧讲解", "generator":"minimax"}
        with patch.object(self.cw.config,"minimax_enabled",return_value=True), patch.object(self.cw,"_compose_ai_explanation",side_effect=model):
            try:
                self.cw.reveal_session_question(self.session_id); self.assertTrue(entered.wait(1))
                self.cw.close_session_question(self.session_id)
                self.cw.launch_session_question(self.session_id, question_id="qb_pop_1", stage_id="s1", delivery="student")
            finally:
                release.set(); self.wait_finished()
        active=self.store.get_class_session(self.session_id).active_question
        self.assertFalse(active["timer"]["revealed"])
        self.assertIsNone(active["timer"]["ai_explanation"])

    def test_interrupted_request_retries_without_duplicate_reveal_event(self):
        self.cw.reveal_session_question(self.session_id)
        active=self.store.get_class_session(self.session_id).active_question
        active["timer"].update(ai_explanation=None,ai_explanation_status="pending",ai_request_id="old-process")
        self.store.set_active_question(self.session_id,active)
        self.assertEqual(self.cw.get_question_explanation(self.session_id)["timer"]["ai_explanation_status"],"interrupted")
        result=self.cw.reveal_session_question(self.session_id)
        self.assertEqual(result["timer"]["ai_explanation_status"],"ready")
        self.assertEqual(sum(e["type"]=="question_revealed" for e in self.store.get_class_session(self.session_id).events),1)

    def test_busy_model_slots_return_reference_notes_instead_of_queueing(self):
        self.cw._explanation_slots.acquire(); self.cw._explanation_slots.acquire()
        try:
            with patch.object(self.cw.config,"minimax_enabled",return_value=True), patch.object(self.cw,"_compose_ai_explanation") as compose:
                result=self.cw.reveal_session_question(self.session_id)
                compose.assert_not_called()
                self.assertEqual(result["timer"]["ai_explanation_status"],"ready")
                self.assertIn("繁忙",result["timer"]["ai_explanation_note"])
                self.assertEqual(result["ai_explanation"]["generator"],"rules")
        finally:
            self.cw._explanation_slots.release(); self.cw._explanation_slots.release()

    def test_ended_class_does_not_receive_a_worker_result(self):
        entered, release=threading.Event(),threading.Event()
        def model(question):
            entered.set(); release.wait(3)
            return {"text":"过期结果","generator":"minimax"}
        with patch.object(self.cw.config,"minimax_enabled",return_value=True), patch.object(self.cw,"_compose_ai_explanation",side_effect=model):
            try:
                self.cw.reveal_session_question(self.session_id); self.assertTrue(entered.wait(1))
                self.cw.end_class_session(self.session_id)
            finally:
                release.set(); self.wait_finished()
        self.assertEqual(self.store.get_class_session(self.session_id).status,"ended")
        self.assertNotIn("过期结果",str(self.store.get_class_session(self.session_id).active_question))
