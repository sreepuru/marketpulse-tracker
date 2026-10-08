"""
MarketPulse V9 - AI Prediction / Human Feedback API Router

Integrate in src/backend/api.py:

    from ai_feedback_api_v9 import router as ai_feedback_router
    app.include_router(ai_feedback_router)

Or, when running the package from src.backend:

    from src.backend.ai_feedback_api_v9 import router as ai_feedback_router
    app.include_router(ai_feedback_router)

Requires the V9 SQL migration to have been applied first.
"""

from typing import Any, Optional

import os
import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api", tags=["AI Feedback"])


DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": os.getenv("MARKETPULSE_DB_PORT", "5432"),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}


def get_connection():
    return psycopg.connect(**DB_CONFIG)


class AIPredictionCreate(BaseModel):
    news_id: int
    model_name: str = Field(min_length=1, max_length=120)
    model_version: Optional[str] = Field(default=None, max_length=120)
    predicted_event_type: Optional[str] = Field(default=None, max_length=100)
    predicted_event_status: Optional[str] = Field(default=None, max_length=30)
    predicted_direction: Optional[str] = Field(default=None, max_length=30)
    predicted_impact_level: Optional[str] = Field(default=None, max_length=30)
    model_confidence: Optional[float] = None
    prediction_reason: Optional[str] = None
    key_facts: Optional[dict[str, Any]] = None
    input_text_hash: Optional[str] = Field(default=None, max_length=64)
    input_text_chars: Optional[int] = None
    prediction_status: str = Field(default="PREDICTED", max_length=30)


class AIFeedbackCreate(BaseModel):
    prediction_id: int
    news_id: int

    event_correct: Optional[bool] = None
    direction_correct: Optional[bool] = None
    impact_correct: Optional[bool] = None

    corrected_event_type: Optional[str] = Field(default=None, max_length=100)
    corrected_event_status: Optional[str] = Field(default=None, max_length=30)
    corrected_direction: Optional[str] = Field(default=None, max_length=30)
    corrected_impact_level: Optional[str] = Field(default=None, max_length=30)

    correction_reason: Optional[str] = None

    reviewer_type: str = Field(default="HUMAN", max_length=30)


@router.get("/news/{news_id}/ai")
def get_news_ai(news_id: int):
    """
    Return the latest AI prediction(s) and any human feedback
    for one market_news record.
    """
    prediction_query = """
        SELECT
            p.prediction_id,
            p.news_id,
            p.model_name,
            p.model_version,
            p.predicted_event_type,
            p.predicted_event_status,
            p.predicted_direction,
            p.predicted_impact_level,
            p.model_confidence,
            p.prediction_reason,
            p.key_facts,
            p.input_text_hash,
            p.input_text_chars,
            p.prediction_status,
            p.predicted_at,
            f.feedback_id,
            f.review_status,
            f.event_correct,
            f.direction_correct,
            f.impact_correct,
            f.corrected_event_type,
            f.corrected_event_status,
            f.corrected_direction,
            f.corrected_impact_level,
            f.correction_reason,
            f.reviewer_type,
            f.reviewed_at

        FROM market_news_ai_predictions p

        LEFT JOIN LATERAL (
            SELECT *
            FROM market_news_ai_feedback f2
            WHERE f2.prediction_id = p.prediction_id
            ORDER BY f2.reviewed_at DESC, f2.feedback_id DESC
            LIMIT 1
        ) f
            ON TRUE

        WHERE p.news_id = %s

        ORDER BY p.predicted_at DESC, p.prediction_id DESC;
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    prediction_query,
                    (news_id,),
                )
                rows = cur.fetchall()

        columns = [
            "prediction_id",
            "news_id",
            "model_name",
            "model_version",
            "predicted_event_type",
            "predicted_event_status",
            "predicted_direction",
            "predicted_impact_level",
            "model_confidence",
            "prediction_reason",
            "key_facts",
            "input_text_hash",
            "input_text_chars",
            "prediction_status",
            "predicted_at",
            "feedback_id",
            "review_status",
            "event_correct",
            "direction_correct",
            "impact_correct",
            "corrected_event_type",
            "corrected_event_status",
            "corrected_direction",
            "corrected_impact_level",
            "correction_reason",
            "reviewer_type",
            "reviewed_at",
        ]

        data = [
            dict(zip(columns, row))
            for row in rows
        ]

        return {
            "status": "success",
            "news_id": news_id,
            "count": len(data),
            "data": data,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to load AI prediction: {exc}",
        )


@router.post("/news/ai-predictions")
def create_ai_prediction(payload: AIPredictionCreate):
    """
    Store a model prediction without modifying market_news.
    This preserves prediction history for later evaluation/training.
    """
    query = """
        INSERT INTO market_news_ai_predictions (
            news_id,
            model_name,
            model_version,
            predicted_event_type,
            predicted_event_status,
            predicted_direction,
            predicted_impact_level,
            model_confidence,
            prediction_reason,
            key_facts,
            input_text_hash,
            input_text_chars,
            prediction_status
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
        RETURNING
            prediction_id,
            news_id,
            model_name,
            model_version,
            predicted_event_type,
            predicted_event_status,
            predicted_direction,
            predicted_impact_level,
            model_confidence,
            prediction_status,
            predicted_at;
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        payload.news_id,
                        payload.model_name,
                        payload.model_version,
                        payload.predicted_event_type,
                        payload.predicted_event_status,
                        payload.predicted_direction,
                        payload.predicted_impact_level,
                        payload.model_confidence,
                        payload.prediction_reason,
                        payload.key_facts,
                        payload.input_text_hash,
                        payload.input_text_chars,
                        payload.prediction_status,
                    ),
                )

                row = cur.fetchone()
                conn.commit()

        columns = [
            "prediction_id",
            "news_id",
            "model_name",
            "model_version",
            "predicted_event_type",
            "predicted_event_status",
            "predicted_direction",
            "predicted_impact_level",
            "model_confidence",
            "prediction_status",
            "predicted_at",
        ]

        return {
            "status": "success",
            "data": dict(zip(columns, row)),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to create AI prediction: {exc}",
        )


@router.post("/news/ai-feedback")
def create_ai_feedback(payload: AIFeedbackCreate):
    """
    Store human review/correction separately from model output.

    Training data should be derived from reviewed/corrected values,
    not directly from model predictions.
    """
    verify_query = """
        SELECT news_id
        FROM market_news_ai_predictions
        WHERE prediction_id = %s;
    """

    insert_query = """
        INSERT INTO market_news_ai_feedback (
            prediction_id,
            news_id,
            review_status,
            event_correct,
            direction_correct,
            impact_correct,
            corrected_event_type,
            corrected_event_status,
            corrected_direction,
            corrected_impact_level,
            correction_reason,
            reviewer_type
        )
        VALUES (
            %s, %s, 'REVIEWED',
            %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
        RETURNING
            feedback_id,
            prediction_id,
            news_id,
            review_status,
            reviewed_at;
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    verify_query,
                    (payload.prediction_id,),
                )
                existing = cur.fetchone()

                if not existing:
                    raise HTTPException(
                        status_code=404,
                        detail="AI prediction not found.",
                    )

                if existing[0] != payload.news_id:
                    raise HTTPException(
                        status_code=400,
                        detail="news_id does not match prediction_id.",
                    )

                cur.execute(
                    insert_query,
                    (
                        payload.prediction_id,
                        payload.news_id,
                        payload.event_correct,
                        payload.direction_correct,
                        payload.impact_correct,
                        payload.corrected_event_type,
                        payload.corrected_event_status,
                        payload.corrected_direction,
                        payload.corrected_impact_level,
                        payload.correction_reason,
                        payload.reviewer_type,
                    ),
                )

                row = cur.fetchone()
                conn.commit()

        columns = [
            "feedback_id",
            "prediction_id",
            "news_id",
            "review_status",
            "reviewed_at",
        ]

        return {
            "status": "success",
            "data": dict(zip(columns, row)),
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to save AI feedback: {exc}",
        )


@router.get("/ai-training/summary")
def ai_training_summary():
    """
    Basic training-data readiness metrics.
    This does not train anything.
    """
    query = """
        SELECT
            COUNT(*) AS prediction_count
        FROM market_news_ai_predictions;
    """

    feedback_query = """
        SELECT
            COUNT(*) AS feedback_count,
            COUNT(*) FILTER (
                WHERE event_correct = TRUE
            ) AS event_correct_count,
            COUNT(*) FILTER (
                WHERE event_correct = FALSE
            ) AS event_wrong_count
        FROM market_news_ai_feedback;
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                predictions = cur.fetchone()

                cur.execute(feedback_query)
                feedback = cur.fetchone()

        return {
            "status": "success",
            "predictions": {
                "total": predictions[0] or 0,
            },
            "feedback": {
                "total": feedback[0] or 0,
                "event_correct": feedback[1] or 0,
                "event_wrong": feedback[2] or 0,
            },
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to load AI training summary: {exc}",
        )