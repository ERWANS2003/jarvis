"""Mode revision : « Jarvis, interroge-moi sur la Révolution française ».

Le modele pose les questions et juge les reponses ; ce module tient le
score et rappelle les regles a chaque tour tant que le quiz dure. Pendant un
quiz, Jarvis ecoute plus longtemps apres chaque question (le temps de
reflechir) et garde ses outils pour noter chaque reponse.
"""

from __future__ import annotations

import threading

FOLLOW_UP_SECONDS = 15.0   # temps pour repondre a une question, sans « Jarvis »

RULES = {
    "fr": ("MODE QUIZ ACTIF sur « {topic} » : question {asked}/{total}, score {score}. "
           "Pose UNE question courte a la fois (QCM a trois choix ou reponse en un mot), "
           "puis attends. Quand l'utilisateur repond : appelle record_quiz_answer(correct), "
           "dis s'il a raison avec une explication d'une phrase, puis pose la question "
           "suivante. S'il dit « stop » ou « arrete le quiz », appelle stop_quiz."),
    "en": ("QUIZ MODE ON about '{topic}': question {asked}/{total}, score {score}. "
           "Ask ONE short question at a time (three-choice or one-word answer), then wait. "
           "When the user answers: call record_quiz_answer(correct), say whether it is "
           "right with a one-sentence explanation, then ask the next question. If they "
           "say 'stop', call stop_quiz."),
}


class QuizSession:
    """Etat du quiz en cours (un seul a la fois), sur entre fils."""

    def __init__(self, lang: str = "fr"):
        self.lang = "fr" if lang == "fr" else "en"
        self._lock = threading.Lock()
        self.topic = ""
        self.total = 0
        self.asked = 0
        self.score = 0

    @property
    def active(self) -> bool:
        return bool(self.topic)

    def start(self, topic: str, questions: int = 5) -> str:
        with self._lock:
            self.topic = " ".join((topic or "culture générale").split())[:80]
            self.total = min(max(int(questions or 5), 1), 20)
            self.asked = self.score = 0
        return self.rules() + (" Commence par une phrase d'accueil, puis la question 1."
                               if self.lang == "fr" else
                               " Start with a one-line welcome, then question 1.")

    def record(self, correct: bool) -> str:
        with self._lock:
            if not self.active:
                return "No quiz is running."
            self.asked += 1
            self.score += 1 if correct else 0
            if self.asked < self.total:
                return (f"Score {self.score}/{self.asked}. Pose la question {self.asked + 1}."
                        if self.lang == "fr" else
                        f"Score {self.score}/{self.asked}. Ask question {self.asked + 1}.")
            summary = self._finish()
        return summary

    def stop(self) -> str:
        with self._lock:
            if not self.active:
                return "No quiz is running."
            return self._finish()

    def _finish(self) -> str:
        score, asked, topic = self.score, self.asked, self.topic
        self.topic, self.total, self.asked, self.score = "", 0, 0, 0
        if self.lang == "fr":
            return (f"Quiz termine sur « {topic} » : {score}/{asked}. Annonce le score, "
                    "felicite ou encourage en une phrase, et propose de revoir un point rate.")
        return (f"Quiz over on '{topic}': {score}/{asked}. Announce the score, praise or "
                "encourage in one sentence, and offer to review a missed point.")

    def rules(self) -> str:
        if not self.active:
            return ""
        return RULES[self.lang].format(topic=self.topic, asked=self.asked + 1,
                                       total=self.total, score=self.score)


def active_quiz(args):
    """Le quiz en cours (via le contexte des outils), ou None."""
    quiz = getattr(getattr(args, "tool_ctx", None), "quiz", None)
    return quiz if quiz is not None and quiz.active else None


def rules_for(args) -> str:
    """Consigne a ajouter au prompt systeme ("" sans quiz en cours)."""
    quiz = active_quiz(args)
    return quiz.rules() if quiz is not None else ""


__all__ = ["QuizSession", "active_quiz", "rules_for", "FOLLOW_UP_SECONDS"]
