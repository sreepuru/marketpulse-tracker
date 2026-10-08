import React, { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../config";
import "../NewsAIInsights.css";

const EVENT_OPTIONS = [
    "OTHER",
    "DIVIDEND",
    "BOARD_MEETING",
    "FINANCIAL_RESULT",
    "ORDER_WIN",
    "ACQUISITION",
    "SHAREHOLDING_CHANGE",
    "BUYBACK",
    "PREFERENTIAL_ISSUE",
    "RIGHTS_ISSUE",
    "BONUS_ISSUE",
    "STOCK_SPLIT",
    "INTEREST_PAYMENT",
    "DEBENTURE_REDEMPTION",
    "DEBT_ISSUANCE",
    "DEBT_REPAYMENT",
    "APPOINTMENT",
    "RESIGNATION",
    "MANAGEMENT_CHANGE",
    "REGULATORY_PENALTY",
    "SHOW_CAUSE_NOTICE",
    "REGULATORY_ORDER",
    "LITIGATION",
    "SETTLEMENT",
    "CREDIT_RATING",
    "INSOLVENCY",
    "ANALYST_MEETING",
    "INVESTOR_MEETING",
    "NAV_UPDATE",
];

const STATUS_OPTIONS = [
    "UPCOMING",
    "CONFIRMED",
    "COMPLETED",
    "NOT_SURE",
];

const DIRECTION_OPTIONS = [
    "POSITIVE",
    "NEGATIVE",
    "NEUTRAL",
    "NOT_SURE",
];

const IMPACT_OPTIONS = [
    "HIGH",
    "MEDIUM",
    "LOW",
    "NOT_SURE",
];

function displayLabel(value) {
    if (!value) {
        return "Not Sure";
    }

    return String(value)
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/\b\w/g, (character) =>
            character.toUpperCase()
        );
}

function normalizeConfidence(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return null;
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return null;
    }

    if (number >= 0 && number <= 1) {
        return number * 100;
    }

    return number;
}

function formatPercent(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function formatRatio(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return `${number.toFixed(2)}x`;
}

function confidenceClass(value) {
    const confidence = normalizeConfidence(value);

    if (confidence === null) {
        return "unknown";
    }

    if (confidence >= 80) {
        return "high";
    }

    if (confidence >= 60) {
        return "medium";
    }

    return "low";
}

function directionClass(value) {
    switch (String(value || "").toUpperCase()) {
        case "POSITIVE":
            return "positive";
        case "NEGATIVE":
            return "negative";
        default:
            return "neutral";
    }
}

function assessmentClass(value) {
    switch (String(value || "").toUpperCase()) {
        case "CONFIRMED":
            return "confirmed";
        case "UNRESOLVED":
            return "unresolved";
        case "CONTRADICTED":
            return "contradicted";
        default:
            return "unknown";
    }
}

export default function NewsAIInsights({ item }) {
    const [prediction, setPrediction] = useState(null);
    const [loading, setLoading] = useState(false);
    const [running, setRunning] = useState(false);
    const [error, setError] = useState("");

    const [eventCorrect, setEventCorrect] = useState(null);
    const [directionCorrect, setDirectionCorrect] =
        useState(null);
    const [impactCorrect, setImpactCorrect] = useState(null);

    const [correctEvent, setCorrectEvent] = useState("OTHER");
    const [correctStatus, setCorrectStatus] =
        useState("NOT_SURE");
    const [correctDirection, setCorrectDirection] =
        useState("NOT_SURE");
    const [correctImpact, setCorrectImpact] =
        useState("NOT_SURE");
    const [reviewNote, setReviewNote] = useState("");

    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);

    const newsId = item?.news_id;

    const latest = useMemo(() => {
        if (!prediction) {
            return null;
        }

        if (
            Array.isArray(prediction.data) &&
            prediction.data.length
        ) {
            return prediction.data[0];
        }

        if (prediction.prediction) {
            return prediction.prediction;
        }

        return null;
    }, [prediction]);

    useEffect(() => {
        let cancelled = false;

        async function loadPrediction() {
            if (!newsId) {
                return;
            }

            setLoading(true);
            setError("");
            setSaved(false);

            try {
                const response = await fetch(
                    `${API_BASE_URL}/api/news/${newsId}/ai`
                );

                if (!response.ok) {
                    throw new Error(
                        `AI lookup failed (${response.status})`
                    );
                }

                const result = await response.json();

                if (!cancelled) {
                    setPrediction(result);
                }
            } catch (err) {
                if (!cancelled) {
                    console.error(
                        "AI prediction lookup error:",
                        err
                    );
                    setPrediction(null);
                    setError(
                        err?.message ||
                        "Unable to load AI prediction."
                    );
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        loadPrediction();

        return () => {
            cancelled = true;
        };
    }, [newsId]);

    useEffect(() => {
        if (!latest) {
            return;
        }

        setCorrectEvent(
            latest.predicted_event_type || "OTHER"
        );

        setCorrectStatus(
            latest.predicted_event_status || "NOT_SURE"
        );

        setCorrectDirection(
            latest.predicted_direction || "NOT_SURE"
        );

        setCorrectImpact(
            latest.predicted_impact_level || "NOT_SURE"
        );

        setEventCorrect(
            latest.event_correct ??
            null
        );

        setDirectionCorrect(
            latest.direction_correct ??
            null
        );

        setImpactCorrect(
            latest.impact_correct ??
            null
        );
    }, [latest]);

    async function generatePrediction() {
        if (!newsId) {
            return;
        }

        setRunning(true);
        setError("");
        setSaved(false);

        try {
            const response = await fetch(
                `${API_BASE_URL}/api/news/${newsId}/ai/predict`,
                {
                    method: "POST",
                }
            );

            const result = await response.json();

            if (!response.ok) {
                throw new Error(
                    result?.detail ||
                    `AI prediction failed (${response.status})`
                );
            }

            setPrediction({
                status: "success",
                count: 1,
                data: [result.prediction],
                prediction: result.prediction,
                outcome: result.outcome,
                assessment: result.assessment,
            });

            setCorrectEvent(
                result.prediction?.event_type ||
                "OTHER"
            );

            setCorrectStatus(
                result.prediction?.event_status ||
                "NOT_SURE"
            );

            setCorrectDirection(
                result.prediction?.direction ||
                "NOT_SURE"
            );

            setCorrectImpact(
                result.prediction?.impact_level ||
                "NOT_SURE"
            );

            if (result.outcome) {
                setPrediction((current) => ({
                    ...current,
                    outcome: result.outcome,
                    assessment: result.assessment,
                }));
            }
        } catch (err) {
            console.error(
                "Generate AI prediction error:",
                err
            );

            setError(
                err?.message ||
                "Unable to generate AI prediction."
            );
        } finally {
            setRunning(false);
        }
    }

    async function saveFeedback() {
        if (!latest?.prediction_id) {
            setError(
                "No prediction is available to review."
            );
            return;
        }

        setSaving(true);
        setSaved(false);
        setError("");

        try {
            const response = await fetch(
                `${API_BASE_URL}/api/news/ai-feedback`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                    },
                    body: JSON.stringify({
                        prediction_id:
                            latest.prediction_id,
                        news_id: newsId,

                        event_correct:
                            eventCorrect,
                        direction_correct:
                            directionCorrect,
                        impact_correct:
                            impactCorrect,

                        corrected_event_type:
                            correctEvent,
                        corrected_event_status:
                            correctStatus,
                        corrected_direction:
                            correctDirection,
                        corrected_impact_level:
                            correctImpact,

                        correction_reason:
                            reviewNote.trim() ||
                            null,

                        reviewer_type: "HUMAN",
                    }),
                }
            );

            const result = await response.json();

            if (!response.ok) {
                throw new Error(
                    result?.detail ||
                    `Feedback failed (${response.status})`
                );
            }

            setSaved(true);
        } catch (err) {
            console.error(
                "AI feedback error:",
                err
            );

            setError(
                err?.message ||
                "Unable to save feedback."
            );
        } finally {
            setSaving(false);
        }
    }

    if (!item) {
        return null;
    }

    return (
        <section className="news-ai-insights">
            <div className="news-ai-header">
                <div>
                    <span className="news-ai-kicker">
                        MARKETPULSE AI
                    </span>
                    <h3>
                        AI Prediction &amp; Market Outcome
                    </h3>
                </div>

                <button
                    type="button"
                    className="news-ai-run"
                    onClick={generatePrediction}
                    disabled={running}
                >
                    {running
                        ? "Analyzing..."
                        : latest
                            ? "Re-run AI"
                            : "Run AI Prediction"}
                </button>
            </div>

            {loading && (
                <div className="news-ai-state">
                    Loading AI prediction...
                </div>
            )}

            {error && (
                <div className="news-ai-error">
                    {error}
                </div>
            )}

            {!loading && !latest && !running && (
                <div className="news-ai-empty">
                    AI prediction has not been generated
                    for this filing yet.
                </div>
            )}

            {latest && (
                <>
                    <div className="news-ai-grid">
                        <div className="news-ai-metric">
                            <span>Event</span>
                            <strong>
                                {displayLabel(
                                    latest.predicted_event_type
                                )}
                            </strong>
                        </div>

                        <div className="news-ai-metric">
                            <span>Status</span>
                            <strong>
                                {displayLabel(
                                    latest.predicted_event_status
                                )}
                            </strong>
                        </div>

                        <div className="news-ai-metric">
                            <span>Direction</span>
                            <strong
                                className={directionClass(
                                    latest.predicted_direction
                                )}
                            >
                                {displayLabel(
                                    latest.predicted_direction
                                )}
                            </strong>
                        </div>

                        <div className="news-ai-metric">
                            <span>Impact</span>
                            <strong>
                                {displayLabel(
                                    latest.predicted_impact_level
                                )}
                            </strong>
                        </div>

                        <div className="news-ai-metric">
                            <span>Confidence</span>
                            <strong
                                className={
                                    confidenceClass(
                                        latest.model_confidence
                                    )
                                }
                            >
                                {normalizeConfidence(
                                    latest.model_confidence
                                )?.toFixed(1) ??
                                    "—"}
                                %
                            </strong>
                        </div>
                    </div>

                    {latest.prediction_reason && (
                        <div className="news-ai-reason">
                            <span>Model reasoning</span>
                            <p>
                                {latest.prediction_reason}
                            </p>
                        </div>
                    )}

                    {latest.key_facts &&
                        Array.isArray(
                            latest.key_facts
                        ) &&
                        latest.key_facts.length > 0 && (
                            <div className="news-ai-facts">
                                <span>Key facts</span>
                                <ul>
                                    {latest.key_facts
                                        .slice(0, 5)
                                        .map(
                                            (
                                                fact,
                                                index
                                            ) => (
                                                <li
                                                    key={
                                                        index
                                                    }
                                                >
                                                    {
                                                        fact
                                                    }
                                                </li>
                                            )
                                        )}
                                </ul>
                            </div>
                        )}

                    {prediction.outcome && (
                        <div className="news-ai-outcome">
                            <div className="news-ai-subheading">
                                Observed Market Outcome
                            </div>

                            <div className="news-ai-outcome-grid">
                                <div>
                                    <span>
                                        1D Return
                                    </span>
                                    <strong>
                                        {formatPercent(
                                            prediction
                                                .outcome
                                                .stock_return_1d
                                        )}
                                    </strong>
                                </div>

                                <div>
                                    <span>
                                        3D Return
                                    </span>
                                    <strong>
                                        {formatPercent(
                                            prediction
                                                .outcome
                                                .stock_return_3d
                                        )}
                                    </strong>
                                </div>

                                <div>
                                    <span>
                                        5D Return
                                    </span>
                                    <strong>
                                        {formatPercent(
                                            prediction
                                                .outcome
                                                .stock_return_5d
                                        )}
                                    </strong>
                                </div>

                                <div>
                                    <span>
                                        Volume
                                    </span>
                                    <strong>
                                        {formatRatio(
                                            prediction
                                                .outcome
                                                .volume_ratio_1d
                                        )}
                                    </strong>
                                </div>
                            </div>

                            {prediction.assessment && (
                                <div className="news-ai-assessment">
                                    <div>
                                        <span>
                                            Automatic
                                            assessment
                                        </span>

                                        <strong
                                            className={assessmentClass(
                                                prediction
                                                    .assessment
                                                    .auto_assessment
                                            )}
                                        >
                                            {displayLabel(
                                                prediction
                                                    .assessment
                                                    .auto_assessment
                                            )}
                                        </strong>
                                    </div>

                                    <div>
                                        <span>
                                            Possible
                                            explanation
                                        </span>

                                        <strong>
                                            {displayLabel(
                                                prediction
                                                    .assessment
                                                    .possible_explanation
                                            )}
                                        </strong>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    <div className="news-ai-feedback">
                        <div className="news-ai-subheading">
                            Human Validation
                        </div>

                        <div className="news-ai-review-grid">
                            {[
                                [
                                    "Event",
                                    eventCorrect,
                                    setEventCorrect,
                                ],
                                [
                                    "Direction",
                                    directionCorrect,
                                    setDirectionCorrect,
                                ],
                                [
                                    "Impact",
                                    impactCorrect,
                                    setImpactCorrect,
                                ],
                            ].map(
                                ([
                                    title,
                                    value,
                                    setter,
                                ]) => (
                                    <div
                                        key={title}
                                    >
                                        <span>
                                            {title}
                                        </span>

                                        <div className="news-ai-review-buttons">
                                            <button
                                                type="button"
                                                className={
                                                    value ===
                                                    true
                                                        ? "selected-correct"
                                                        : ""
                                                }
                                                onClick={() =>
                                                    setter(
                                                        true
                                                    )
                                                }
                                            >
                                                Correct
                                            </button>

                                            <button
                                                type="button"
                                                className={
                                                    value ===
                                                    false
                                                        ? "selected-wrong"
                                                        : ""
                                                }
                                                onClick={() =>
                                                    setter(
                                                        false
                                                    )
                                                }
                                            >
                                                Wrong
                                            </button>
                                        </div>
                                    </div>
                                )
                            )}
                        </div>

                        <div className="news-ai-correction-grid">
                            <label>
                                Correct Event
                                <select
                                    value={
                                        correctEvent
                                    }
                                    onChange={(event) =>
                                        setCorrectEvent(
                                            event.target
                                                .value
                                        )
                                    }
                                >
                                    {EVENT_OPTIONS.map(
                                        (option) => (
                                            <option
                                                key={
                                                    option
                                                }
                                                value={
                                                    option
                                                }
                                            >
                                                {displayLabel(
                                                    option
                                                )}
                                            </option>
                                        )
                                    )}
                                </select>
                            </label>

                            <label>
                                Correct Status
                                <select
                                    value={
                                        correctStatus
                                    }
                                    onChange={(event) =>
                                        setCorrectStatus(
                                            event.target
                                                .value
                                        )
                                    }
                                >
                                    {STATUS_OPTIONS.map(
                                        (option) => (
                                            <option
                                                key={
                                                    option
                                                }
                                                value={
                                                    option
                                                }
                                            >
                                                {displayLabel(
                                                    option
                                                )}
                                            </option>
                                        )
                                    )}
                                </select>
                            </label>

                            <label>
                                Correct Direction
                                <select
                                    value={
                                        correctDirection
                                    }
                                    onChange={(event) =>
                                        setCorrectDirection(
                                            event.target
                                                .value
                                        )
                                    }
                                >
                                    {DIRECTION_OPTIONS.map(
                                        (option) => (
                                            <option
                                                key={
                                                    option
                                                }
                                                value={
                                                    option
                                                }
                                            >
                                                {displayLabel(
                                                    option
                                                )}
                                            </option>
                                        )
                                    )}
                                </select>
                            </label>

                            <label>
                                Correct Impact
                                <select
                                    value={
                                        correctImpact
                                    }
                                    onChange={(event) =>
                                        setCorrectImpact(
                                            event.target
                                                .value
                                        )
                                    }
                                >
                                    {IMPACT_OPTIONS.map(
                                        (option) => (
                                            <option
                                                key={
                                                    option
                                                }
                                                value={
                                                    option
                                                }
                                            >
                                                {displayLabel(
                                                    option
                                                )}
                                            </option>
                                        )
                                    )}
                                </select>
                            </label>
                        </div>

                        <label className="news-ai-note">
                            Review note
                            <textarea
                                rows="3"
                                value={reviewNote}
                                onChange={(event) =>
                                    setReviewNote(
                                        event.target.value
                                    )
                                }
                                placeholder="Explain why the prediction is correct or wrong."
                            />
                        </label>

                        <div className="news-ai-save-row">
                            <button
                                type="button"
                                className="news-ai-save"
                                onClick={
                                    saveFeedback
                                }
                                disabled={saving}
                            >
                                {saving
                                    ? "Saving..."
                                    : "Save Validation"}
                            </button>

                            {saved && (
                                <span className="news-ai-saved">
                                    Validation saved
                                </span>
                            )}
                        </div>
                    </div>
                </>
            )}

            <div className="news-ai-footnote">
                AI prediction, market outcome and human
                validation are stored separately. A price move
                against the prediction is not automatically
                treated as model failure.
            </div>
        </section>
    );
}