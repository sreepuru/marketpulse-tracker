import React, { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../config";
import "../News.css";

const PAGE_SIZE = 10;

const CATEGORY_CONFIG = [
  { key: "BOARD_MEETING", label: "Board Meetings", icon: "▣" },
  { key: "ANNOUNCEMENT", label: "Announcements", icon: "◈" },
  { key: "CORPORATE_ACTION", label: "Corporate Actions", icon: "◆" },
  { key: "FINANCIAL_RESULT", label: "Financial Results", icon: "▤" },
  { key: "NOTICE", label: "Notices", icon: "◇" },
];

const IMPACT_LEVELS = ["HIGH", "MEDIUM", "LOW", "NOT_SURE"];

const HORIZONS = [
  {
    key: "1d",
    label: "+1D",
    prediction: "ml_1d_predicted_direction",
    score: "ml_1d_prediction_score",
    negative: "ml_1d_negative_probability",
    neutral: "ml_1d_neutral_probability",
    positive: "ml_1d_positive_probability",
    predictedAt: "ml_1d_predicted_at",
    actualReturn: "actual_return_plus_1d",
    actualDirection: "actual_direction_plus_1d",
    actualAvailable: "actual_outcome_available_1d",
  },
  {
    key: "5d",
    label: "+5D",
    prediction: "ml_5d_predicted_direction",
    score: "ml_5d_prediction_score",
    negative: "ml_5d_negative_probability",
    neutral: "ml_5d_neutral_probability",
    positive: "ml_5d_positive_probability",
    predictedAt: "ml_5d_predicted_at",
    actualReturn: "actual_return_plus_5d",
    actualDirection: "actual_direction_plus_5d",
    actualAvailable: "actual_outcome_available_5d",
  },
  {
    key: "10d",
    label: "+10D",
    prediction: "ml_10d_predicted_direction",
    score: "ml_10d_prediction_score",
    negative: "ml_10d_negative_probability",
    neutral: "ml_10d_neutral_probability",
    positive: "ml_10d_positive_probability",
    predictedAt: "ml_10d_predicted_at",
    actualReturn: "actual_return_plus_10d",
    actualDirection: "actual_direction_plus_10d",
    actualAvailable: "actual_outcome_available_10d",
  },
];

const BACKWARD_HORIZONS = [
  {
    key: "10d",
    label: "-10D",
    field: "actual_return_minus_10d",
  },
  {
    key: "5d",
    label: "-5D",
    field: "actual_return_minus_5d",
  },
  {
    key: "1d",
    label: "-1D",
    field: "actual_return_minus_1d",
  },
];

const NON_EQUITY_ASSETS = new Set([
  "MUTUAL_FUND",
  "ETF",
  "BOND",
  "OTHER",
]);

const ASSET_CATEGORY_OPTIONS = [
  "ALL",
  "EQUITY",
  "MUTUAL_FUND",
  "ETF",
  "BOND",
  "OTHER",
  "UNCLASSIFIED",
];

function SecurityEventCard({
  item,
  onSelect,
}) {
  const lifecycle = getEventLifecycle(item);

  const mappingStatus = String(
    item?.mapping_status || ""
  ).toUpperCase();

  const mappingConfidence = Number(
    item?.mapping_confidence
  );

  const mappingStatusLabel =
    mappingStatus === "MAPPED"
      ? Number.isFinite(mappingConfidence)
        ? `Mapped (${Math.round(mappingConfidence * 100)}%)`
        : "Mapped"
      : mappingStatus || "Not mapped";

  const pipelineStatus = pipelineStatusLabel(item);

  const pipelineDetail =
    pipelineReasonDetail(item);

  const mappedSecurityId =
    item?.security_id ?? "—";

  const mappingMethod =
    item?.mapping_method || "—";

  const mappedOn =
    item?.mapped_at ||
    item?.mapping_updated_at ||
    item?.updated_at ||
    null;

  const mappedBy =
    item?.mapped_by ||
    item?.mapping_reviewer ||
    (
      mappingMethod === "USER_CONFIRMED"
        ? "User"
        : mappingMethod !== "—"
        ? mappingMethod
        : "—"
    );

  const assetCategory =
    getAssetCategory(item);

  return (
    <article
      className="security-event-card"
      onClick={() => onSelect(item)}
    >

      {/* =====================================================
          EVENT HEADER - SINGLE LINE
          ===================================================== */}
      <div className="security-event-header compact-event-header">

        <div className="event-header-type">
          <span className="event-type-label">
            {item.category ||
              item.ai_event_type ||
              "MARKET EVENT"}
          </span>

          <span
            className={`asset-tag asset-${getAssetTagClass(item)}`}
          >
            {assetCategory}
          </span>
        </div>

        <h4 className="event-header-title">
          {item.title || "Untitled market event"}
        </h4>

        <div className="event-announcement-inline">
          <span>ANNOUNCEMENT</span>
          <strong>{formatDate(lifecycle.announcementDate)}</strong>
          <small>{formatTime(lifecycle.announcementDate)}</small>
        </div>

      </div>


      {/* =====================================================
          MAIN EVENT DATA
          ===================================================== */}
      <div className="event-main-grid">

        {/* -------------------------------------------------
            DATE & EVENT INFORMATION
            ------------------------------------------------- */}
        <section className="event-information-panel">

          <div className="event-panel-title">
            EVENT DETAILS
          </div>

          <div className="event-detail-grid">

            <div className="event-detail-item">
              <span>{getEventLifecycleLabel(item)}</span>

              <strong>
                {formatLifecycleDate(lifecycle.validUntil)}
              </strong>
            </div>

            <div className="event-detail-item">
              <span>Event Type</span>

              <strong>
                {item.category ||
                  item.ai_event_type ||
                  "Announcement"}
              </strong>
            </div>

            <div className="event-detail-item event-detail-wide">
              <span>Summary</span>

              <p>
                {item.description
                  ? truncate(item.description, 240)
                  : "No summary available."}
              </p>
            </div>

          </div>

        </section>


        {/* -------------------------------------------------
            MARKET PREDICTION
            ------------------------------------------------- */}
        <section className="event-prediction-panel">

          <div className="event-panel-title">
            MARKET PREDICTION
            <small>
              LightGBM
            </small>
          </div>

          <div
            className="security-prediction-row"
            onClick={(event) =>
              event.stopPropagation()
            }
          >
            {HORIZONS.map((horizon) => (
              <PredictionMini
                key={horizon.key}
                item={item}
                horizon={horizon}
              />
            ))}
          </div>

        </section>


        {/* -------------------------------------------------
            EVENT VALIDITY
            ------------------------------------------------- */}
        <section className="event-validity-panel">

          <div className="event-panel-title">
            EVENT VALIDITY
          </div>

          <div className="event-validity-list">

            <div>
              <span>
                {getEventLifecycleLabel(item)}
              </span>

              <strong>
                {formatLifecycleDate(lifecycle.validUntil)}
              </strong>
            </div>

            <div>
              <span>Validity Source</span>

              <strong>
                {lifecycle.validitySource || "—"}
              </strong>
            </div>

          </div>

        </section>

      </div>


      {/* =====================================================
          EVENT IDENTIFICATION / MAPPING / PIPELINE
          ===================================================== */}
      <div className="event-system-information">

        <div className="event-system-section-title">
          EVENT IDENTIFICATION & PROCESSING
        </div>

        <div className="event-system-grid">

          {/* NEWS ID */}
          <div className="event-system-item">

            <span className="event-system-label">
              NEWS ID
            </span>

            <strong>
              {item.news_id ?? "—"}
            </strong>

          </div>


          {/* MAPPED SECURITY ID */}
          <div className="event-system-item">

            <span className="event-system-label">
              MAPPED SECURITY ID
            </span>

            <strong>
              {mappedSecurityId}
            </strong>

          </div>


          {/* MAPPING STATUS */}
          <div className="event-system-item">

            <span className="event-system-label">
              MAPPING STATUS
            </span>

            <strong
              className={
                mappingStatus === "MAPPED"
                  ? "status-success"
                  : "status-warning"
              }
            >
              {mappingStatusLabel}
            </strong>

          </div>


          {/* MAPPING METHOD */}
          <div className="event-system-item">

            <span className="event-system-label">
              MAPPING METHOD
            </span>

            <strong>
              {mappingMethod}
            </strong>

          </div>


          {/* MAPPED ON */}
          <div className="event-system-item">

            <span className="event-system-label">
              MAPPED ON
            </span>

            <strong>
              {formatDateTime(mappedOn)}
            </strong>

          </div>


          {/* MAPPED BY */}
          <div className="event-system-item">

            <span className="event-system-label">
              MAPPED BY
            </span>

            <strong>
              {mappedBy}
            </strong>

          </div>


          {/* PIPELINE */}
          <div className="event-system-item">

            <span className="event-system-label">
              PIPELINE
            </span>

            <strong>
              {pipelineStatus}
            </strong>

          </div>


          {/* PIPELINE DETAIL */}
          <div className="event-system-item">

            <span className="event-system-label">
              PIPELINE DETAIL
            </span>

            <strong>
              {pipelineDetail ||
                "—"}
            </strong>

          </div>

        </div>

      </div>


      {/* =====================================================
          FOOTER
          ===================================================== */}
      <div className="security-event-footer">

        <span>
          Prediction Engine:
          <strong>
            {" "}LightGBM
          </strong>
        </span>

        <span>
          1D / 5D / 10D
        </span>

        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onSelect(item);
          }}
        >
          View Details →
        </button>

      </div>

    </article>
  );
}

function getAssetCategory(item) {
  const value = String(item?.asset_category || "").trim().toUpperCase();
  return value || "UNCLASSIFIED";
}

function getAssetTagClass(item) {
  return getAssetCategory(item)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function isMapped(item) {
  return String(item?.mapping_status || "").toUpperCase() === "MAPPED";
}

function isNonEquity(item) {
  return NON_EQUITY_ASSETS.has(getAssetCategory(item));
}

// A successfully mapped security is treated as an equity event for the
// presentation layer unless it has an explicit non-equity asset category.
// This prevents mapped equity events from leaking into the exceptions tab
// merely because the asset_category field has not yet been backfilled.
function isEquityEvent(item) {
  return isMapped(item) && !isNonEquity(item);
}

function isExceptionEvent(item) {
  return !isMapped(item);
}

function hasAiPrediction(item) {
  return Boolean(
    item?.ml_1d_predicted_direction ||
    item?.ml_5d_predicted_direction ||
    item?.ml_10d_predicted_direction ||
    item?.ai_predicted_direction ||
    item?.direction
  );
}

function predictionStatus(item, horizon) {
  return String(item?.[`ml_${horizon.key}_prediction_status`] || "").toUpperCase() || "NOT_AVAILABLE";
}

function predictionStatusLabel(status) {
  const labels = {
    AVAILABLE: "Available",
    NOT_MAPPED: "Not mapped",
    NO_HISTORY: "No price history",
    INSUFFICIENT_HISTORY: "Insufficient history",
    NO_FEATURES: "Features unavailable",
    NO_PREDICTION: "Prediction unavailable",
    NO_PUBLISHED_AT: "No publication time",
  };
  return labels[status] || "Not available";
}


function pipelineStatusLabel(item) {
  const status = String(item?.pipeline_pit_status || "").toUpperCase();
  const reason = String(item?.pipeline_pit_reason || "").toUpperCase();

  if (reason) {
    const labels = {
      NO_HISTORY: "No price history",
      INSUFFICIENT_HISTORY: "Insufficient history",
      NOT_MAPPED: "Not mapped",
      NO_PUBLISHED_AT: "No publication time",
      NOT_APPLICABLE: "Not applicable",
      FEATURES_NOT_BUILT: "Features not built",
      PREDICTION_INELIGIBLE: "Prediction ineligible",
      HISTORY_AVAILABLE: "History available",
    };
    return labels[reason] || reason.replaceAll("_", " ");
  }

  if (status) return status.replaceAll("_", " ");
  return "Not audited";
}

function pipelineReasonDetail(item) {
  return item?.pipeline_pit_reason_detail ||
    item?.pipeline_feature_reason_detail ||
    "";
}

function toDateOnly(value) {
  if (!value) return null;

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate()
  );
}

function formatLifecycleDate(value) {
  if (!value) return "—";

  const date = toDateOnly(value);

  if (!date) return "—";

  return date.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/*
 * Current event lifecycle.
 *
 * Priority:
 *   1. record_date
 *   2. valid_until
 *   3. announcement_date + 7 days
 *
 * At the moment the existing API provides published_at as the
 * announcement timestamp. The backend can later provide
 * record_date / valid_until explicitly.
 */
function getEventLifecycle(item) {
  const announcementDate =
    item?.announcement_date ||
    item?.published_at ||
    null;

  const recordDate =
    item?.record_date ||
    null;

  const explicitValidUntil =
    item?.valid_until ||
    null;

  const announcement =
    toDateOnly(announcementDate);

  const record =
    toDateOnly(recordDate);

  const explicit =
    toDateOnly(explicitValidUntil);

  let validUntil = null;
  let validitySource = null;
  let validityLabel = null;

  if (record) {
    validUntil = record;
    validitySource = "RECORD_DATE";
    validityLabel = "Record Date";
  } else if (explicit) {
    validUntil = explicit;
    validitySource = "EVENT_VALID_DATE";
    validityLabel =
      item?.valid_until_label ||
      "Valid Until";
  } else if (item?.meeting_date) {
    validUntil = toDateOnly(item.meeting_date);
    validitySource = "MEETING_DATE";
    validityLabel = "Meeting Date";
  } else if (item?.event_date) {
    validUntil = toDateOnly(item.event_date);
    validitySource = "EVENT_DATE";
    validityLabel = "Event Date";
  } else if (item?.effective_date) {
    validUntil = toDateOnly(item.effective_date);
    validitySource = "EFFECTIVE_DATE";
    validityLabel = "Effective Date";
  } else if (announcement) {
    validUntil = announcement;
    validitySource = "ANNOUNCEMENT_DATE";
    validityLabel = "Announcement Date";
  }

  return {
    announcementDate: announcement,
    recordDate: record,
    validUntil,
    validitySource,
    validityLabel,
  };
}

function isCurrentEvent(item) {
  const lifecycle =
    getEventLifecycle(item);

  if (!lifecycle.validUntil) {
    return true;
  }

  const today = new Date();

  const todayOnly = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate()
  );

  return (
    lifecycle.validUntil >= todayOnly
  );
}

function getEventLifecycleLabel(item) {
  const lifecycle =
    getEventLifecycle(item);

  if (
    lifecycle.validitySource ===
    "RECORD_DATE"
  ) {
    return "Record Date";
  }

  if (
    lifecycle.validitySource ===
    "EVENT_VALID_DATE"
  ) {
    return lifecycle.validityLabel;
  }

  if (lifecycle.validityLabel) {
    return lifecycle.validityLabel;
  }

  return "Validity";
}

function normaliseCategory(value = "") {
  const v = String(value).toUpperCase().replace(/[\s-]+/g, "_");

  if (v.includes("BOARD")) return "BOARD_MEETING";
  if (v.includes("CORPORATE")) return "CORPORATE_ACTION";
  if (v.includes("FINANCIAL") || v.includes("RESULT")) {
    return "FINANCIAL_RESULT";
  }
  if (v.includes("NOTICE")) return "NOTICE";

  return "ANNOUNCEMENT";
}

function normaliseImpact(value) {
  const v = String(value || "").toUpperCase();
  return IMPACT_LEVELS.includes(v) ? v : "NOT_SURE";
}

function normaliseDirection(value) {
  const v = String(value || "").toUpperCase();

  if (
    ["POSITIVE", "NEGATIVE", "NEUTRAL", "NOT_SURE"].includes(v)
  ) {
    return v;
  }

  return "NOT_SURE";
}

function formatDate(value) {
  if (!value) return "—";

  const d = new Date(value);

  if (Number.isNaN(d.getTime())) {
    return String(value);
  }

  return d.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function formatTime(value) {
  if (!value) return "";

  const d = new Date(value);

  if (Number.isNaN(d.getTime())) {
    return "";
  }

  return d.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateTime(value) {
  if (!value) return "—";

  return `${formatDate(value)} ${formatTime(value)}`;
}

function truncate(text, length = 180) {
  if (!text) return "";

  return text.length > length
    ? `${text.slice(0, length).trim()}…`
    : text;
}

function formatPercent(value, digits = 2) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  return `${n.toFixed(digits)}%`;
}

function formatProbability(value) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return "—";
  }

  return `${(n * 100).toFixed(1)}%`;
}

function getExchangeTag(item) {
  const exchange = String(item.exchange || "").toUpperCase();

  if (exchange === "NSE") return "NSE";
  if (exchange === "BSE") return "BSE";

  return exchange || "—";
}

function getDirectionClass(value) {
  const direction = normaliseDirection(value);

  return `direction-${direction.toLowerCase()}`;
}

function getOutcome(item, horizon) {
  const prediction = normaliseDirection(
    item[horizon.prediction]
  );

  const actualAvailable = item[horizon.actualAvailable];

  const actualDirection = normaliseDirection(
    item[horizon.actualDirection]
  );

  if (
    actualAvailable === true &&
    actualDirection !== "NOT_SURE"
  ) {
    if (prediction === actualDirection) {
      return "CORRECT";
    }

    return "DIFFERENT";
  }

  return "PENDING";
}

function getOutcomeLabel(outcome) {
  switch (outcome) {
    case "CORRECT":
      return "Matched";
    case "DIFFERENT":
      return "Different";
    default:
      return "Pending";
  }
}

function ImpactBox({
  level,
  count,
  active,
  onClick,
}) {
  const labels = {
    HIGH: "High",
    MEDIUM: "Medium",
    LOW: "Low",
    NOT_SURE: "Not Sure",
  };

  return (
    <button
      type="button"
      className={`impact-box impact-${level.toLowerCase()} ${
        active ? "active" : ""
      }`}
      onClick={onClick}
    >
      <span className="impact-box-count">{count}</span>
      <span className="impact-box-label">
        {labels[level]}
      </span>
    </button>
  );
}

function CategoryCard({
  config,
  items,
  activeImpact,
  onImpact,
}) {
  const counts = IMPACT_LEVELS.reduce(
    (acc, level) => {
      acc[level] = items.filter(
        (item) =>
          normaliseImpact(item.impact_level) === level
      ).length;

      return acc;
    },
    {
      HIGH: 0,
      MEDIUM: 0,
      LOW: 0,
      NOT_SURE: 0,
    }
  );

  return (
    <section className="intelligence-category-card">
      <div className="category-card-heading">
        <div className="category-icon">
          {config.icon}
        </div>

        <div>
          <span className="category-kicker">
            CATEGORY
          </span>

          <h3>{config.label}</h3>
        </div>

        <span className="category-total">
          {items.length}
        </span>
      </div>

      <div className="impact-grid">
        {IMPACT_LEVELS.map((level) => (
          <ImpactBox
            key={level}
            level={level}
            count={counts[level]}
            active={activeImpact === level}
            onClick={() =>
              onImpact(
                activeImpact === level
                  ? "ALL"
                  : level
              )
            }
          />
        ))}
      </div>
    </section>
  );
}

function PredictionMini({
  item,
  horizon,
}) {
  const direction = normaliseDirection(
    item[horizon.prediction]
  );

  const score = item[horizon.score];
  const status = predictionStatus(item, horizon);
  const predictionAvailable = status === "AVAILABLE";

  const actualAvailable =
    item[horizon.actualAvailable] === true;

  const actualDirection = normaliseDirection(
    item[horizon.actualDirection]
  );

  const actualReturn = item[horizon.actualReturn];

  const outcome = getOutcome(item, horizon);

  return (
    <div className="prediction-mini">
      <div className="prediction-mini-header">
        <span>{horizon.label}</span>

        <span
          className={`prediction-mini-direction ${getDirectionClass(
            direction
          )}`}
        >
          {predictionAvailable && direction !== "NOT_SURE"
            ? direction
            : "—"}
        </span>
      </div>

      <div className="prediction-mini-score">
        {predictionAvailable ? formatProbability(score) : "—"}
      </div>

      <div className="prediction-mini-label">
        {predictionAvailable
          ? "Prediction confidence"
          : predictionStatusLabel(status)}
      </div>

      <div
        className={`prediction-mini-outcome outcome-${outcome.toLowerCase()}`}
      >
        {actualAvailable ? (
          <>
            <span>
              Actual{" "}
              {Number.isFinite(Number(actualReturn))
                ? formatPercent(
                    Number(actualReturn) * 100
                  )
                : "—"}
            </span>

            <strong>
              {actualDirection}
            </strong>
          </>
        ) : (
          <>
            <span>Actual</span>
            <strong>Pending</strong>
          </>
        )}
      </div>
    </div>
  );
}

function SecurityIntelligenceCard({
  security,
  onSelect,
  onHistory,
}) {
  const currentEvents = security.currentEvents || [];
  const historyEvents = security.historyEvents || [];
  const latestEvent = currentEvents[0] || historyEvents[0] || null;

  return (
    <section className="security-intelligence-card">
      <div className="security-card-header">
        <div>
          <div className="security-card-title-row">
            <h3>{security.security_name}</h3>
            {security.symbol && <span className="symbol-tag">{security.symbol}</span>}
            {security.exchange && <span className="exchange-tag">{security.exchange}</span>}
            {security.asset_category && security.asset_category !== "UNCLASSIFIED" && (
              <span className={`asset-tag asset-${getAssetTagClass({ asset_category: security.asset_category })}`}>
                {security.asset_category}
              </span>
            )}
          </div>
          <span className="security-card-subtitle">
            {currentEvents.length} current · {historyEvents.length} historical
          </span>
        </div>

        {historyEvents.length > 0 && (
          <button
            type="button"
            className="history-button"
            onClick={() => onHistory(security)}
          >
            View History →
          </button>
        )}
      </div>

      <div className="security-current-events">
        {currentEvents.length > 0 ? (
          currentEvents.map((item) => (
            <SecurityEventCard key={item.news_id} item={item} onSelect={onSelect} />
          ))
        ) : latestEvent ? (
          <div className="security-latest-event">
            <div className="security-latest-label">
              LATEST EVENT · {formatDate(latestEvent.published_at)}
            </div>
            <SecurityEventCard item={latestEvent} onSelect={onSelect} />
          </div>
        ) : (
          <div className="security-empty-current">No event available</div>
        )}
      </div>
    </section>
  );
}

function HistoryPanel({ security, onClose, onSelect }) {
  if (!security) return null;

  const events = [
    ...(security.currentEvents || []),
    ...(security.historyEvents || []),
  ].sort(
    (a, b) => new Date(b.published_at || 0) - new Date(a.published_at || 0)
  );

  return (
    <div className="news-detail-overlay" onClick={onClose}>
      <aside className="news-detail-panel" onClick={(event) => event.stopPropagation()}>
        <div className="detail-top">
          <div>
            <div className="detail-tags">
              {security.exchange && <span className="exchange-tag">{security.exchange}</span>}
              {security.symbol && <span className="symbol-tag">{security.symbol}</span>}
              {security.asset_category && <span className="asset-tag">{security.asset_category}</span>}
            </div>
            <h2>{security.security_name}</h2>
            <div className="detail-date">
              {events.length} events · current {security.currentEvents?.length || 0} · history {security.historyEvents?.length || 0}
            </div>
          </div>
          <button type="button" className="close-detail" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="detail-section-heading">
          <div>
            <span>EVENT HISTORY</span>
            <h3>All announcements and predictions</h3>
          </div>
          <small>LightGBM +1D / +5D / +10D</small>
        </div>

        <div className="history-event-list">
          {events.map((item) => (
            <SecurityEventCard
              key={item.news_id}
              item={item}
              onSelect={(eventItem) => {
                onClose();
                onSelect(eventItem);
              }}
            />
          ))}
        </div>
      </aside>
    </div>
  );
}

function NewsRow({
  item,
  onSelect,
}) {
  const direction = normaliseDirection(
    item.direction
  );

  const impact = normaliseImpact(
    item.impact_level
  );

  return (
    <button
      type="button"
      className="insight-row"
      onClick={() => onSelect(item)}
    >
      <div className="insight-date">
        <strong>
          {formatDate(item.published_at)}
        </strong>

        <span>
          {formatTime(item.published_at)}
        </span>

        <span>
          News ID: {item.news_id ?? "—"}
        </span>

        <span>
          Mapping: {item.mapping_status || "—"}
        </span>
      </div>

      <div className="insight-main">
        <div className="insight-meta">
          <span
            className={`exchange-tag exchange-${getExchangeTag(
              item
            ).toLowerCase()}`}
          >
            {getExchangeTag(item)}
          </span>

          {item.symbol && (
            <span className="symbol-tag">
              {item.symbol}
            </span>
          )}

          <span
            className={`asset-tag asset-${getAssetTagClass(item)}`}
          >
            {getAssetCategory(item)}
          </span>

          <span
            className={`mapping-pill mapping-${String(
              item.mapping_status || "UNKNOWN"
            ).toLowerCase()}`}
          >
            {isMapped(item) ? "MAPPED" : "NOT MAPPED"}
          </span>

          <span
            className={`impact-pill impact-pill-${impact.toLowerCase()}`}
          >
            {impact === "NOT_SURE"
              ? "NOT SURE"
              : impact}
          </span>

          <span
            className={`direction-pill ${getDirectionClass(
              direction
            )}`}
          >
            {direction === "NOT_SURE"
              ? "DIRECTION PENDING"
              : direction}
          </span>
        </div>

        <h4>
          {item.title ||
            "Untitled market filing"}
        </h4>

        <div className="insight-company">
          {item.company_name ||
            "Company not mapped"}
        </div>

        {item.description && (
          <p>
            {truncate(item.description)}
          </p>
        )}
      </div>

      <div className="row-predictions">
        {HORIZONS.map((horizon) => (
          <PredictionMini
            key={horizon.key}
            item={item}
            horizon={horizon}
          />
        ))}
      </div>

      <div className="pipeline-status-mini">
        <span className="pipeline-status-label">Pipeline</span>
        <strong>{pipelineStatusLabel(item)}</strong>
        {pipelineReasonDetail(item) && (
          <small>{pipelineReasonDetail(item)}</small>
        )}
      </div>

      <div className="insight-arrow">
        →
      </div>
    </button>
  );
}

function BackwardMovement({
  item,
}) {
  return (
    <div className="backward-section">
      <div className="detail-section-heading">
        <div>
          <span>PRE-EVENT</span>
          <h3>Actual price movement</h3>
        </div>

        <small>
          Historical movement before the event
        </small>
      </div>

      <div className="backward-grid">
        {BACKWARD_HORIZONS.map((horizon) => {
          const value = item[horizon.field];

          return (
            <div
              className="backward-card"
              key={horizon.key}
            >
              <span className="horizon-label">
                {horizon.label}
              </span>

              <strong
                className={
                  Number(value) > 0
                    ? "return-positive"
                    : Number(value) < 0
                    ? "return-negative"
                    : "return-neutral"
                }
              >
                {Number.isFinite(Number(value))
                  ? formatPercent(
                      Number(value) * 100
                    )
                  : "—"}
              </strong>

              <small>Actual</small>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PredictionCard({
  item,
  horizon,
}) {
  const direction = normaliseDirection(
    item[horizon.prediction]
  );

  const score = item[horizon.score];
  const status = predictionStatus(item, horizon);
  const predictionAvailable = status === "AVAILABLE";

  const negative =
    item[horizon.negative];

  const neutral =
    item[horizon.neutral];

  const positive =
    item[horizon.positive];

  const actualAvailable =
    item[horizon.actualAvailable] === true;

  const actualDirection =
    normaliseDirection(
      item[horizon.actualDirection]
    );

  const actualReturn =
    item[horizon.actualReturn];

  const outcome = getOutcome(
    item,
    horizon
  );

  return (
    <div className="horizon-prediction-card">
      <div className="horizon-card-top">
        <div>
          <span className="horizon-card-label">
            {horizon.label}
          </span>

          <small>
            Market reaction prediction
          </small>
        </div>

        <span
          className={`horizon-direction ${getDirectionClass(
            direction
          )}`}
        >
          {predictionAvailable && direction !== "NOT_SURE"
            ? direction
            : "NOT AVAILABLE"}
        </span>
      </div>

      <div className="horizon-score">
        {predictionAvailable ? formatProbability(score) : "—"}
      </div>

      <div className="horizon-score-label">
        {predictionAvailable ? "Prediction confidence" : predictionStatusLabel(status)}
      </div>

      {predictionAvailable && <div className="probability-list">
        <div>
          <span>Negative</span>
          <strong>
            {formatProbability(negative)}
          </strong>
        </div>

        <div>
          <span>Neutral</span>
          <strong>
            {formatProbability(neutral)}
          </strong>
        </div>

        <div>
          <span>Positive</span>
          <strong>
            {formatProbability(positive)}
          </strong>
        </div>
      </div>}

      {!predictionAvailable && (
        <div className="prediction-status-tag">
          {predictionStatusLabel(status)}
        </div>
      )}

      <div className="actual-result">
        <span className="actual-result-label">
          Observed outcome
        </span>

        {actualAvailable ? (
          <div className="actual-result-value">
            <strong
              className={getDirectionClass(
                actualDirection
              )}
            >
              {actualDirection}
            </strong>

            <span
              className={
                Number(actualReturn) > 0
                  ? "return-positive"
                  : Number(actualReturn) < 0
                  ? "return-negative"
                  : "return-neutral"
              }
            >
              {Number.isFinite(
                Number(actualReturn)
              )
                ? formatPercent(
                    Number(actualReturn) * 100
                  )
                : "—"}
            </span>
          </div>
        ) : (
          <div className="actual-pending">
            Actual Pending
          </div>
        )}

        {outcome !== "PENDING" && (
          <span
            className={`outcome-badge outcome-${outcome.toLowerCase()}`}
          >
            {getOutcomeLabel(outcome)}
          </span>
        )}
      </div>

      {item[horizon.predictedAt] && (
        <div className="prediction-timestamp">
          Prediction generated{" "}
          {formatDateTime(
            item[horizon.predictedAt]
          )}
        </div>
      )}
    </div>
  );
}

function PostEventPredictions({
  item,
}) {
  return (
    <div className="post-event-section">
      <div className="detail-section-heading">
        <div>
          <span>POST-EVENT</span>
          <h3>Market reaction prediction</h3>
        </div>

        <small>
          ML prediction vs observed outcome
        </small>
      </div>

      <div className="prediction-grid">
        {HORIZONS.map((horizon) => (
          <PredictionCard
            key={horizon.key}
            item={item}
            horizon={horizon}
          />
        ))}
      </div>
    </div>
  );
}


function isAgentPredicted(item) {
  return Boolean(
    item?.agent_decision_id ||
    item?.agent_decision ||
    item?.agent_predicted_security_id
  );
}

function AgentPredictionPanel({ item, feedback, onFeedback }) {
  if (!isAgentPredicted(item)) return null;

  const agentSecurityId = item?.agent_predicted_security_id;
  const decision = String(item?.agent_decision || "PENDING").toUpperCase();
  const reviewed = feedback?.verdict;

  return (
    <section className="mapping-feedback-section">
      <div className="detail-section-heading">
        <div>
          <span>AGENT REVIEW</span>
          <h3>Mapping Agent decision</h3>
        </div>
        <small>Human validation</small>
      </div>

      <div className="agent-prediction-summary">
        <div><span>Decision</span><strong>{decision}</strong></div>
        <div><span>Agent security</span><strong>{agentSecurityId || "No security proposed"}</strong></div>
        <div><span>Confidence</span><strong>{item?.agent_prediction_confidence != null ? formatPercent(Number(item.agent_prediction_confidence) * 100, 1) : "—"}</strong></div>
      </div>

      {reviewed ? (
        <div className={`feedback-result feedback-result-${reviewed.toLowerCase()}`}>
          {reviewed === "CORRECT" ? "✓ Prediction marked correct" : "✕ Prediction marked wrong"}
        </div>
      ) : (
        <div className="mapping-feedback-actions">
          <button
            type="button"
            className="feedback-button feedback-correct"
            disabled={!agentSecurityId}
            onClick={() => onFeedback({ verdict: "CORRECT" })}
            title={!agentSecurityId ? "This Agent decision has no proposed security." : "Mark the Agent prediction correct"}
          >
            ✓ Correct
          </button>
          <button
            type="button"
            className="feedback-button feedback-wrong"
            onClick={() => onFeedback({ verdict: "WRONG" })}
          >
            ✕ Wrong
          </button>
        </div>
      )}
    </section>
  );
}

function ManualMapping({ item, onMapped }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [selectedSecurity, setSelectedSecurity] = useState(null);
  const [alias, setAlias] = useState(item?.company_name || "");
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [manualError, setManualError] = useState("");

  useEffect(() => {
    setQuery("");
    setResults([]);
    setSelectedSecurity(null);
    setAlias(item?.company_name || "");
    setMessage("");
    setManualError("");
  }, [item?.news_id]);

  const searchSecurities = async () => {
    const value = query.trim();
    if (!value) return;

    try {
      setSearching(true);
      setManualError("");

      const response = await fetch(
        `${API_BASE_URL}/api/stock/search?q=${encodeURIComponent(value)}`
      );

      if (!response.ok) {
        throw new Error(`Security search returned ${response.status}`);
      }

      const payload = await response.json();
      setResults(Array.isArray(payload.data) ? payload.data : []);
    } catch (err) {
      setResults([]);
      setManualError(err.message || "Unable to search securities.");
    } finally {
      setSearching(false);
    }
  };

  const saveMapping = async () => {
    if (!selectedSecurity?.security_id) return;

    try {
      setSaving(true);
      setManualError("");
      setMessage("");

      const response = await fetch(`${API_BASE_URL}/api/mapping/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          news_id: item.news_id,
          security_id: selectedSecurity.security_id,
          reviewer: "USER",
          alias: alias.trim() || item.company_name || null,
        }),
      });

      const payload = await response.json();

      if (!response.ok) {
        throw new Error(payload.detail || `Manual mapping returned ${response.status}`);
      }

      setMessage(`Mapped to ${selectedSecurity.symbol || selectedSecurity.instrument_name || selectedSecurity.security_id}.`);
      onMapped({
        ...item,
        security_id: selectedSecurity.security_id,
        mapping_status: "MAPPED",
        mapping_method: "USER_CONFIRMED",
        mapping_confidence: 1,
        company_name: item.company_name || selectedSecurity.instrument_name,
      });
    } catch (err) {
      setManualError(err.message || "Unable to save mapping.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="manual-mapping-section">
      <div className="detail-section-heading">
        <div>
          <span>MANUAL MAPPING</span>
          <h3>Set canonical security</h3>
        </div>
        <small>Uses security_master</small>
      </div>

      <div className="manual-mapping-search">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") searchSecurities();
          }}
          placeholder="Search symbol, company, ISIN or instrument ID"
        />
        <button type="button" onClick={searchSecurities} disabled={searching || !query.trim()}>
          {searching ? "Searching…" : "Search"}
        </button>
      </div>

      {results.length > 0 && (
        <div className="manual-mapping-results">
          {results.map((security) => (
            <button
              type="button"
              key={security.security_id}
              className={`manual-mapping-result ${selectedSecurity?.security_id === security.security_id ? "selected" : ""}`}
              onClick={() => setSelectedSecurity(security)}
            >
              <strong>{security.symbol || security.instrument_name || "—"}</strong>
              <span>{security.instrument_name || "—"}</span>
              <small>
                ID {security.security_id} · {security.exchange || "—"} · {security.isin || "No ISIN"}
              </small>
            </button>
          ))}
        </div>
      )}

      {selectedSecurity && (
        <div className="manual-mapping-confirm">
          <div>
            <strong>
              Selected: {selectedSecurity.symbol || selectedSecurity.instrument_name}
            </strong>
            <small>security_id: {selectedSecurity.security_id}</small>
          </div>

          <label>
            Identity / alias
            <input
              value={alias}
              onChange={(event) => setAlias(event.target.value)}
              placeholder="Company name or alias"
            />
          </label>

          <button type="button" onClick={saveMapping} disabled={saving}>
            {saving ? "Saving…" : "Confirm Mapping"}
          </button>
        </div>
      )}

      {message && <div className="feedback-result feedback-result-correct">✓ {message}</div>}
      {manualError && <div className="news-error">{manualError}</div>}
    </section>
  );
}

function TargetedMapper({ item, onMapped }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [mapperError, setMapperError] = useState("");

  const canMap = Boolean(item?.news_id);

  const runMapper = async () => {
    if (!canMap) return;

    try {
      setRunning(true);
      setMapperError("");
      setResult(null);

      const response = await fetch(
        `${API_BASE_URL}/api/mapping/run-event`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            news_id: item.news_id,
          }),
        }
      );

      const payload = await response.json();

      if (!response.ok) {
        throw new Error(
          payload.detail ||
            `Mapper returned ${response.status}`
        );
      }

      setResult(payload);

      /*
       * Only treat the event as mapped when the backend
       * confirms MAPPED.
       */
      if (
        String(payload.mapping_status || "")
          .toUpperCase() === "MAPPED"
      ) {
        if (onMapped) {
          onMapped({
            ...item,
            ...payload,

            mapping_status: "MAPPED",

            security_id:
              payload.security?.security_id ??
              payload.security_id ??
              item.security_id,

            mapping_method:
              payload.mapping_method ??
              item.mapping_method,

            mapping_confidence:
              payload.mapping_confidence ??
              item.mapping_confidence,

            mapped_security: payload.security || null,
          });
        }
      }

    } catch (err) {
      setMapperError(
        err.message ||
          "Unable to run security mapper."
      );
    } finally {
      setRunning(false);
    }
  };

  const mapped =
    String(
      result?.mapping_status ||
        item?.mapping_status ||
        ""
    ).toUpperCase() === "MAPPED";

  return (
    <section className="targeted-mapper-section">

      <div className="detail-section-heading">

        <div>
          <span>SECURITY MAPPING</span>

          <h3>
            {mapped
              ? "Security mapped"
              : "Map this event"}
          </h3>
        </div>

        <small>
          Uses canonical security mapper
        </small>

      </div>


      {!mapped && (
        <div className="mapper-pending-message">
          This event is not currently mapped to
          a security master record.
        </div>
      )}


      <div className="mapper-action-row">

        <button
          type="button"
          className="mapper-run-button"
          onClick={runMapper}
          disabled={!canMap || running}
        >
          {running
            ? "Running Mapper…"
            : mapped
            ? "Run Mapper Again"
            : "Run Mapper"}
        </button>

      </div>


      {mapperError && (
        <div className="news-error">
          {mapperError}
        </div>
      )}


      {result && (
        <div className="mapper-result">

          <div className="mapper-result-item">

            <span>
              Mapping Status
            </span>

            <strong>
              {result.mapping_status ||
                "—"}
            </strong>

          </div>


          <div className="mapper-result-item">

            <span>
              Security ID
            </span>

            <strong>
              {result.security_id ??
                "—"}
            </strong>

          </div>


          <div className="mapper-result-item">

            <span>
              Mapping Method
            </span>

            <strong>
              {result.mapping_method ||
                "—"}
            </strong>

          </div>


          <div className="mapper-result-item">

            <span>
              Confidence
            </span>

            <strong>
              {result.mapping_confidence != null
                ? `${(
                    Number(
                      result.mapping_confidence
                    ) * 100
                  ).toFixed(0)}%`
                : "—"}
            </strong>

          </div>


          {(result.security?.instrument_name || result.security_name) && (
            <div className="mapper-result-item">

              <span>
                Security
              </span>

              <strong>
                {result.security?.instrument_name || result.security_name}
              </strong>

            </div>
          )}

        </div>
      )}

    </section>
  );
}


function TargetedModelScore({ item, onScored }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [scoreError, setScoreError] = useState("");

  const canScore =
    Boolean(
      item?.news_id &&
      item?.security_id &&
      String(item?.mapping_status || "").toUpperCase() === "MAPPED"
    );

  const runScore = async () => {
    if (!canScore) return;

    try {
      setRunning(true);
      setScoreError("");
      setResult(null);

      const response = await fetch(`${API_BASE_URL}/api/ml/score-event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ news_id: item.news_id }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || `Model scoring returned ${response.status}`);
      }

      setResult(payload);
      if (onScored) onScored(payload);
    } catch (err) {
      setScoreError(err.message || "Unable to run LightGBM scoring.");
    } finally {
      setRunning(false);
    }
  };

  const horizons = result?.horizons || {};
  const rows = [
    ["+1D", horizons["1D"]],
    ["+5D", horizons["5D"]],
    ["+10D", horizons["10D"]],
  ];

  return (
    <section className="targeted-model-score-section">
      <div className="detail-section-heading">
        <div>
          <span>LIGHTGBM</span>
          <h3>Run score for this event</h3>
        </div>
        <small>Uses the existing trained models; does not retrain.</small>
      </div>

      {!canScore && (
        <div className="actual-pending">
          Run the mapper successfully before running the LightGBM score.
        </div>
      )}

      <button
        type="button"
        className="feedback-button feedback-correct"
        onClick={runScore}
        disabled={!canScore || running}
      >
        {running ? "Running LightGBM…" : "Run LightGBM Score"}
      </button>

      {scoreError && <div className="news-error">{scoreError}</div>}

      {result && (
        <div className="targeted-score-results">
          {rows.map(([label, value]) => (
            <div className="targeted-score-card" key={label}>
              <span>{label}</span>
              <strong>{value?.predicted_direction || "—"}</strong>
              <small>
                Score: {value?.prediction_score != null
                  ? formatPercent(Number(value.prediction_score) * 100, 1)
                  : "—"}
              </small>
              <small>
                Negative {value?.negative_probability != null
                  ? formatPercent(Number(value.negative_probability) * 100, 1)
                  : "—"}
                {" · "}
                Neutral {value?.neutral_probability != null
                  ? formatPercent(Number(value.neutral_probability) * 100, 1)
                  : "—"}
                {" · "}
                Positive {value?.positive_probability != null
                  ? formatPercent(Number(value.positive_probability) * 100, 1)
                  : "—"}
              </small>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function DetailPanel({
  item,
  onClose,
  agentFeedback,
  onAgentFeedback,
  onMapped,
  onScored,
}) {
  if (!item) {
    return null;
  }

  const impact = normaliseImpact(
    item.impact_level
  );

  const direction = normaliseDirection(
    item.direction
  );

  return (
    <div
      className="news-detail-overlay"
      onClick={onClose}
    >
      <aside
        className="news-detail-panel"
        onClick={(event) =>
          event.stopPropagation()
        }
      >
        <div className="detail-top">
          <div className="detail-tags">
            <span className="exchange-tag">
              {getExchangeTag(item)}
            </span>

            {item.symbol && (
              <span className="symbol-tag">
                {item.symbol}
              </span>
            )}

            <span
              className={`impact-pill impact-pill-${impact.toLowerCase()}`}
            >
              {impact}
            </span>
          </div>

          <button
            type="button"
            className="close-detail"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="detail-date">
          {formatDate(item.published_at)}
          {" "}
          {formatTime(item.published_at)}
        </div>

        <div className="detail-company">
          {item.company_name ||
            item.symbol ||
            "Market filing"}
        </div>

        <h2>
          {item.title ||
            "Untitled market filing"}
        </h2>

        {item.description && (
          <p className="detail-description">
            {item.description}
          </p>
        )}

        <div className="detail-analysis-grid">
          <div>
            <span>Exchange</span>
            <strong>
              {getExchangeTag(item)}
            </strong>
          </div>

          <div>
            <span>Symbol</span>
            <strong>
              {item.symbol || "—"}
            </strong>
          </div>

          <div>
            <span>Impact</span>
            <strong>{impact}</strong>
          </div>

          <div>
            <span>Event direction</span>
            <strong>{direction}</strong>
          </div>

          <div>
            <span>Asset type</span>
            <strong>{getAssetCategory(item)}</strong>
          </div>

          <div>
            <span>Mapping</span>
            <strong>
              {isMapped(item)
                ? `MAPPED${item.security_id ? ` · ${item.security_id}` : ""}`
                : item.mapping_status || "NOT MAPPED"}
            </strong>
          </div>

          <div>
            <span>AI prediction</span>
            <strong>
              {hasAiPrediction(item)
                ? "AVAILABLE"
                : "PENDING"}
            </strong>
          </div>
        </div>

        <AgentPredictionPanel
          item={item}
          feedback={agentFeedback}
          onFeedback={onAgentFeedback}
        />

        <ManualMapping
          item={item}
          onMapped={onMapped}
        />

        <TargetedModelScore
          item={item}
          onScored={onScored}
        />

        <div className="ai-prediction-summary">
          <div className="detail-section-heading">
            <div>
              <span>AI INTERPRETATION</span>
              <h3>Announcement prediction</h3>
            </div>
            <small>Runs independently of security mapping</small>
          </div>
          {item.ai_prediction_id ? (
            <div className="ai-prediction-summary-grid">
              <div><span>Event</span><strong>{item.ai_event_type || "NOT_SURE"}</strong></div>
              <div><span>Direction</span><strong>{normaliseDirection(item.ai_predicted_direction)}</strong></div>
              <div><span>Impact</span><strong>{normaliseImpact(item.ai_impact_level)}</strong></div>
              <div><span>Confidence</span><strong>{formatPercent(item.ai_confidence, 0)}</strong></div>
            </div>
          ) : (
            <div className="actual-pending">AI prediction pending</div>
          )}
        </div>

        <BackwardMovement item={item} />

        <PostEventPredictions
          item={item}
        />

        <div className="detail-separation-note">
          <strong>
            How to read this
          </strong>

          <span>
            Pre-event figures are observed historical
            price movements (-10D, -5D, -1D). Post-event
            figures are MarketPulse ML predictions for
            +1D, +5D and +10D. AI prediction is independent
            of security mapping; price analysis requires
            a mapped security and available price history.
          </span>
        </div>

        {item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="source-link"
          >
            Open Original Source →
          </a>
        )}
      </aside>
    </div>
  );
}


function formatNumber(value) {
  return Number(value || 0).toLocaleString("en-IN");
}

function pct(value, total) {
  if (!total) return "0.0%";
  return `${((Number(value || 0) / Number(total)) * 100).toFixed(1)}%`;
}

function DensityDots({ total, groups = [] }) {
  const totalDots = 180;
  let cursor = 0;
  const dots = [];

  groups.forEach((group) => {
    const count = Number(group.value || 0);
    const dotCount = total ? Math.round((count / total) * totalDots) : 0;
    for (let i = 0; i < dotCount; i += 1) {
      dots.push(
        <span
          key={`${group.key}-${i}`}
          className={`density-dot density-${group.key}`}
          title={`${group.label}: ${formatNumber(count)}`}
        />
      );
    }
    cursor += dotCount;
  });

  while (dots.length < totalDots) {
    dots.push(<span key={`empty-${dots.length}`} className="density-dot density-empty" />);
  }

  return <div className="density-grid" aria-label="Event density visualization">{dots}</div>;
}

function FlowNode({ label, value, detail, tone = "default" }) {
  return (
    <div className={`pipeline-flow-node pipeline-flow-${tone}`}>
      <span>{label}</span>
      <strong>{formatNumber(value)}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

function PipelineDashboard({ data, onOpenExceptions }) {
  if (!data) {
    return <div className="pipeline-dashboard-loading">Loading pipeline coverage…</div>;
  }

  const masters = data.masters || {};
  const events = data.events || {};
  const audit = data.audit || {};
  const predictions = data.predictions || {};
  const prices = data.prices || {};
  const features = data.features || {};
  const totalEvents = Number(events.total || 0);

  const eventGroups = [
    { key: "equity", label: "Equity", value: events.equity },
    { key: "mf", label: "Mutual Funds", value: events.mutual_fund },
    { key: "etf", label: "ETF", value: events.etf },
    { key: "bond", label: "Bonds", value: events.bond },
    { key: "other", label: "Others", value: events.other },
    { key: "unmapped", label: "Not mapped", value: events.pending + events.ambiguous },
  ];

  return (
    <div className="pipeline-dashboard">
      <section className="pipeline-control-header">
        <div>
          <span className="section-kicker">CONTROL TOWER</span>
          <h3>MarketPulse data flow & coverage</h3>
          <p>
            A single view of masters, incoming events, mapping, PIT history,
            features and LightGBM coverage. Every branch remains accounted for.
          </p>
        </div>
        <div className="pipeline-freshness">
          <span>Latest data pulled</span>
          <strong>{formatDateTime(data.freshness?.latest_data_pulled_at)}</strong>
          <small>Latest price date: {formatDateTime(data.prices?.latest_price_date)}</small>
        </div>
      </section>

      <section className="pipeline-universe-grid">
        <div className="pipeline-universe-card">
          <span>Security masters</span>
          <strong>{formatNumber(masters.total)}</strong>
          <small>{formatNumber(masters.active)} active</small>
        </div>
        <div className="pipeline-universe-card">
          <span>Market events</span>
          <strong>{formatNumber(events.total)}</strong>
          <small>{formatNumber(events.mapped)} mapped</small>
        </div>
        <div className="pipeline-universe-card">
          <span>Price records</span>
          <strong>{formatNumber(prices.price_rows)}</strong>
          <small>{formatNumber(prices.securities_with_prices)} securities</small>
        </div>
        <div className="pipeline-universe-card">
          <span>ML features</span>
          <strong>{formatNumber(features.feature_events)}</strong>
          <small>one row per event</small>
        </div>
      </section>

      <section className="pipeline-section-block">
        <div className="pipeline-section-heading">
          <div>
            <span className="section-kicker">DATA FLOW</span>
            <h4>Events → mapping → PIT → features → scoring</h4>
          </div>
          <span>{pct(audit.fully_scored, totalEvents)} fully scored</span>
        </div>

        <div className="pipeline-flow">
          <FlowNode label="Market events" value={events.total} detail="source universe" tone="blue" />
          <span className="pipeline-flow-arrow">→</span>
          <FlowNode label="Mapped" value={events.mapped} detail={`${pct(events.mapped, totalEvents)} of events`} tone="green" />
          <span className="pipeline-flow-arrow">→</span>
          <FlowNode label="PIT ready" value={audit.feature_ready} detail="history available" tone="purple" />
          <span className="pipeline-flow-arrow">→</span>
          <FlowNode label="Features" value={features.feature_events} detail="event features" tone="orange" />
          <span className="pipeline-flow-arrow">→</span>
          <FlowNode label="1D / 5D / 10D" value={audit.fully_scored} detail="fully scored" tone="dark" />
        </div>

        <div className="pipeline-branch-grid">
          <button type="button" onClick={onOpenExceptions} className="pipeline-branch-card warning">
            <span>NOT MAPPED</span>
            <strong>{formatNumber(audit.not_mapped)}</strong>
            <small>Pending mapping</small>
          </button>
          <div className="pipeline-branch-card">
            <span>INSUFFICIENT HISTORY</span>
            <strong>{formatNumber(audit.insufficient_history)}</strong>
            <small>PIT lookback too short</small>
          </div>
          <div className="pipeline-branch-card">
            <span>NO HISTORY</span>
            <strong>{formatNumber(audit.no_history)}</strong>
            <small>No usable price rows</small>
          </div>
          <div className="pipeline-branch-card">
            <span>NO PUBLISHED AT</span>
            <strong>{formatNumber(audit.no_published_at)}</strong>
            <small>No PIT cutoff</small>
          </div>
        </div>
      </section>

      <section className="pipeline-data-density">
        <div className="pipeline-density-copy">
          <span className="section-kicker">EVENT DENSITY</span>
          <h4>Where the event universe sits</h4>
          <p>
            Each dot represents a proportional slice of the current event universe.
            This is a visual density map, not a second data source.
          </p>
          <div className="density-legend">
            {eventGroups.map((group) => (
              <span key={group.key}>
                <i className={`density-dot density-${group.key}`} />
                {group.label} <strong>{pct(group.value, totalEvents)}</strong>
              </span>
            ))}
          </div>
        </div>
        <DensityDots total={totalEvents} groups={eventGroups} />
      </section>

      <section className="pipeline-category-section">
        <div className="pipeline-section-heading">
          <div>
            <span className="section-kicker">CATEGORY COVERAGE</span>
            <h4>Security masters by asset category</h4>
          </div>
          <span>{formatNumber(masters.total)} total masters</span>
        </div>
        <div className="master-category-grid">
          {[
            ["Equity", masters.equity, "equity"],
            ["Mutual Fund", masters.mutual_fund, "mf"],
            ["ETF", masters.etf, "etf"],
            ["Bond", masters.bond, "bond"],
            ["Other", masters.other, "other"],
          ].map(([label, value, key]) => (
            <div className="master-category-row" key={key}>
              <span>{label}</span>
              <div className="master-category-track">
                <div className={`master-category-fill density-${key}`} style={{ width: `${Math.max(1, (Number(value || 0) / Number(masters.total || 1)) * 100)}%` }} />
              </div>
              <strong>{formatNumber(value)}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="pipeline-prediction-section">
        <div className="pipeline-section-heading">
          <div>
            <span className="section-kicker">PREDICTION COVERAGE</span>
            <h4>LightGBM horizon coverage</h4>
          </div>
          <span>Actual outcomes are tracked separately</span>
        </div>
        <div className="prediction-coverage-grid">
          {[
            ["+1D", predictions.events_1d],
            ["+5D", predictions.events_5d],
            ["+10D", predictions.events_10d],
          ].map(([label, value]) => (
            <div className="prediction-coverage-card" key={label}>
              <span>{label}</span>
              <strong>{formatNumber(value)}</strong>
              <small>{pct(value, audit.feature_ready)} of PIT-ready events</small>
              <div className="coverage-track"><div style={{ width: `${Math.min(100, Number(value || 0) / Number(audit.feature_ready || 1) * 100)}%` }} /></div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function News() {
  const [news, setNews] = useState([]);
  const [total, setTotal] = useState(0);
  const [overview, setOverview] = useState(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [pipelineOverview, setPipelineOverview] = useState(null);
  const [pipelineOverviewLoading, setPipelineOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState("");
  const [pipelineOverviewError, setPipelineOverviewError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [exchange, setExchange] = useState("ALL");
  const [impact, setImpact] = useState("ALL");
  const [category, setCategory] = useState("ALL");
  const [assetCategory, setAssetCategory] = useState("ALL");
  const [feedTab, setFeedTab] = useState("EQUITY");
  const [selectedItem, setSelectedItem] = useState(null);
  const [selectedHistoryGroup, setSelectedHistoryGroup] = useState(null);
  const [mapperOpen, setMapperOpen] = useState(false);
  const [mapperRunningId, setMapperRunningId] = useState(null);
  const [mapperControlError, setMapperControlError] = useState("");
  const [agentFeedback, setAgentFeedback] = useState({});
  const [page, setPage] = useState(1);

  useEffect(() => {
    let cancelled = false;

    async function loadOverview() {
      setOverviewLoading(true);
      setPipelineOverviewLoading(true);
      setOverviewError("");
      setPipelineOverviewError("");

      const [overviewResult, pipelineResult] = await Promise.allSettled([
        fetch(`${API_BASE_URL}/api/news/overview`).then(async (response) => {
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error(payload.detail || `News overview API returned ${response.status}`);
          }
          return payload;
        }),
        fetch(`${API_BASE_URL}/api/news/pipeline-overview`).then(async (response) => {
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error(payload.detail || `Pipeline overview API returned ${response.status}`);
          }
          return payload;
        }),
      ]);

      if (cancelled) return;

      if (overviewResult.status === "fulfilled") {
        setOverview(overviewResult.value);
      } else {
        setOverview(null);
        setOverviewError(overviewResult.reason?.message || "Unable to load market coverage.");
      }

      if (pipelineResult.status === "fulfilled") {
        setPipelineOverview(pipelineResult.value);
      } else {
        setPipelineOverview(null);
        setPipelineOverviewError(pipelineResult.reason?.message || "Unable to load pipeline coverage.");
      }

      setOverviewLoading(false);
      setPipelineOverviewLoading(false);
    }

    loadOverview();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadNews() {
      try {
        setLoading(true);
        setError("");

        const backendCategory = {
          BOARD_MEETING: "BOARD_MEETINGS",
          ANNOUNCEMENT: "ANNOUNCEMENTS",
          CORPORATE_ACTION: "CORPORATE_ACTIONS",
          FINANCIAL_RESULT: "FINANCIAL_RESULTS",
          NOTICE: "NOTICES",
        };

        const params = new URLSearchParams({
          limit: String(
            feedTab === "EQUITY" || feedTab === "NON_EQUITY"
              ? 100
              : PAGE_SIZE
          ),
          offset: String(
            (page - 1) * (
              feedTab === "EQUITY" || feedTab === "NON_EQUITY"
                ? 100
                : PAGE_SIZE
            )
          ),
          exchange,
          category: backendCategory[category] || category,
          impact,
          search: search.trim(),
          feed: feedTab === "PIPELINE" ? "ALL" : feedTab,
        });

        if (
          ["MUTUAL_FUND", "ETF", "BOND", "OTHER", "UNCLASSIFIED"]
            .includes(assetCategory)
        ) {
          params.set("asset_category", assetCategory);
        }

        const response = await fetch(
          `${API_BASE_URL}/api/news?${params.toString()}`
        );

        if (!response.ok) {
          throw new Error(`News API returned ${response.status}`);
        }

        const payload = await response.json();

        if (!cancelled) {
          setNews(Array.isArray(payload.data) ? payload.data : []);
          setTotal(Number(payload.total) || 0);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "Unable to load market news.");
          setNews([]);
          setTotal(0);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadNews();

    return () => {
      cancelled = true;
    };
  }, [
    page,
    feedTab,
    search,
    exchange,
    impact,
    category,
    assetCategory,
  ]);

  useEffect(() => {
    setPage(1);
  }, [search, exchange, impact, category, assetCategory, feedTab]);

  // Filtering, search and global date ordering are performed by /api/news.
  const filteredNews = news;

  const groupedFeedItems = useMemo(() => {
    const groups = new Map();

    for (const item of filteredNews) {
      if (!isMapped(item)) continue;

      const key = item.security_id
        ? `SECURITY:${item.security_id}`
        : `NAME:${getAssetCategory(item)}:${String(
            item.company_name || item.instrument_name || item.symbol || "UNKNOWN"
          ).trim().toUpperCase()}`;

      if (!groups.has(key)) {
        groups.set(key, {
          security_id: item.security_id || null,
          security_name:
            item.company_name || item.instrument_name || item.symbol || "Unknown Security",
          symbol: item.symbol || null,
          exchange: item.exchange || null,
          asset_category: getAssetCategory(item),
          currentEvents: [],
          historyEvents: [],
        });
      }

      const group = groups.get(key);
      if (isCurrentEvent(item)) group.currentEvents.push(item);
      else group.historyEvents.push(item);
    }

    for (const group of groups.values()) {
      const sortEvents = (events) =>
        events.sort(
          (a, b) => new Date(b.published_at || 0) - new Date(a.published_at || 0)
        );
      sortEvents(group.currentEvents);
      sortEvents(group.historyEvents);
    }

    return Array.from(groups.values()).sort((a, b) => {
      const aDate = a.currentEvents[0]?.published_at || a.historyEvents[0]?.published_at || 0;
      const bDate = b.currentEvents[0]?.published_at || b.historyEvents[0]?.published_at || 0;
      return new Date(bDate) - new Date(aDate);
    });
  }, [filteredNews]);

  const summary = useMemo(() => {
    return IMPACT_LEVELS.reduce(
      (acc, level) => {
        acc[level] = filteredNews.filter(
          (item) => normaliseImpact(item.impact_level) === level
        ).length;
        return acc;
      },
      { HIGH: 0, MEDIUM: 0, LOW: 0, NOT_SURE: 0 }
    );
  }, [filteredNews]);

  const categories = useMemo(() => {
    return CATEGORY_CONFIG.map((config) => ({
      ...config,
      items: filteredNews.filter(
        (item) => normaliseCategory(item.category) === config.key
      ),
    }));
  }, [filteredNews]);

  const highImpactItems = useMemo(
    () =>
      filteredNews.filter(
        (item) => normaliseImpact(item.impact_level) === "HIGH"
      ),
    [filteredNews]
  );

  const activeFeedItems = filteredNews;
  const paginatedItems = activeFeedItems;
  const activePageSize =
    feedTab === "EQUITY" || feedTab === "NON_EQUITY" ? 100 : PAGE_SIZE;
  const pageCount = Math.max(1, Math.ceil(total / activePageSize));


  const refreshCurrentFeed = () => {
    setPage(1);
    setError("");
  };

  const openMapper = () => {
    setMapperControlError("");
    setMapperOpen(true);
  };

  const runMapperFromControl = async (item) => {
    if (!item?.news_id || mapperRunningId) return;

    try {
      setMapperRunningId(item.news_id);
      setMapperControlError("");

      const response = await fetch(
        `${API_BASE_URL}/api/mapping/run-event`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            news_id: item.news_id,
          }),
        }
      );

      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          typeof payload.detail === "string"
            ? payload.detail
            : `Mapper returned ${response.status}`
        );
      }

      const security = payload.security || null;
      const updatedItem = {
        ...item,
        mapping_status:
          payload.mapping_status ?? item.mapping_status,
        mapping_method:
          payload.mapping_method ?? item.mapping_method,
        mapping_confidence:
          payload.mapping_confidence ?? item.mapping_confidence,
        security_id:
          security?.security_id ??
          payload.security_id ??
          item.security_id,
        mapped_security: security,
      };

      handleMapped(updatedItem);

      if (
        String(payload.mapping_status || "").toUpperCase() === "MAPPED"
      ) {
        setSelectedItem(updatedItem);
      }
    } catch (err) {
      setMapperControlError(
        err.message || "Unable to run the security mapper."
      );
    } finally {
      setMapperRunningId(null);
    }
  };

  const handleAgentFeedback = async (feedback) => {
    if (!selectedItem?.news_id) return;

    try {
      const payload = {
        news_id: selectedItem.news_id,
        verdict: feedback.verdict,
        wrong_reason: feedback.wrongReason || null,
        comment: feedback.comment || null,
        reviewer: "USER",
        corrected_security_id: feedback.correctedSecurityId || null,
      };

      const response = await fetch(`${API_BASE_URL}/api/mapping/agent-feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.detail || `Agent feedback returned ${response.status}`);
      }

      setAgentFeedback((current) => ({
        ...current,
        [selectedItem.news_id]: {
          ...feedback,
          ...body,
          submittedAt: new Date().toISOString(),
        },
      }));
    } catch (err) {
      setError(err.message || "Unable to save Agent feedback.");
    }
  };

  const handleMapped = (updatedItem) => {
    setSelectedItem(updatedItem);
    setNews((current) =>
      current.map((item) =>
        item.news_id === updatedItem.news_id
          ? { ...item, ...updatedItem }
          : item
      )
    );
  };

  const handleScored = (payload) => {
    const newsId = Number(payload?.news_id);
    if (!newsId) return;

    const horizons = payload.horizons || {};
    const updatedFields = {
      ...(horizons["1D"] ? {
        ml_1d_predicted_direction: horizons["1D"].predicted_direction,
        ml_1d_negative_probability: horizons["1D"].negative_probability,
        ml_1d_neutral_probability: horizons["1D"].neutral_probability,
        ml_1d_positive_probability: horizons["1D"].positive_probability,
        ml_1d_prediction_score: horizons["1D"].prediction_score,
      } : {}),
      ...(horizons["5D"] ? {
        ml_5d_predicted_direction: horizons["5D"].predicted_direction,
        ml_5d_negative_probability: horizons["5D"].negative_probability,
        ml_5d_neutral_probability: horizons["5D"].neutral_probability,
        ml_5d_positive_probability: horizons["5D"].positive_probability,
        ml_5d_prediction_score: horizons["5D"].prediction_score,
      } : {}),
      ...(horizons["10D"] ? {
        ml_10d_predicted_direction: horizons["10D"].predicted_direction,
        ml_10d_negative_probability: horizons["10D"].negative_probability,
        ml_10d_neutral_probability: horizons["10D"].neutral_probability,
        ml_10d_positive_probability: horizons["10D"].positive_probability,
        ml_10d_prediction_score: horizons["10D"].prediction_score,
      } : {}),
    };

    setSelectedItem((current) =>
      current ? { ...current, ...updatedFields } : current
    );
    setNews((current) =>
      current.map((item) =>
        item.news_id === newsId
          ? { ...item, ...updatedFields }
          : item
      )
    );
  };

  return (
    <div className="market-intelligence-page">
      <header className="intelligence-header">
        <div>
          <span className="page-kicker">
            MARKETPULSE
          </span>

          <h1>
            Market Intelligence
          </h1>

          <p>
            NSE + BSE filings in one view,
            organised for market impact,
            direction and price confirmation.
          </p>
        </div>

        <div className="classification-status">
          <span className="status-dot" />

          <div>
            <strong>
              Market reaction intelligence
            </strong>

            <span>
              Prediction + observed outcome
            </span>
          </div>
        </div>
      </header>

      <section className="summary-strip">
        {IMPACT_LEVELS.map(
          (level) => (
            <button
              key={level}
              type="button"
              className={`summary-card summary-${level.toLowerCase()} ${
                impact === level
                  ? "active"
                  : ""
              }`}
              onClick={() =>
                setImpact(
                  impact === level
                    ? "ALL"
                    : level
                )
              }
            >
              <span>
                {summary[level]}
              </span>

              <small>
                {level ===
                "NOT_SURE"
                  ? "Not Sure"
                  : level}
              </small>
            </button>
          )
        )}
      </section>


      {error && (
        <div className="news-error">
          {error}
        </div>
      )}

      {loading ? (
        <div className="news-loading">
          Loading market intelligence…
        </div>
      ) : (
        <>
          <section className="category-section">
            <div className="section-title-row">
              <div>
                <span className="section-kicker">
                  IMPACT MATRIX
                </span>

                <h2>
                  What is happening in the market?
                </h2>
              </div>

              <span className="section-description">
                Click an impact box to filter
                the feed.
              </span>
            </div>

            <div className="category-grid">
              {categories.map(
                (item) => (
                  <CategoryCard
                    key={item.key}
                    config={item}
                    items={item.items}
                    activeImpact={
                      impact
                    }
                    onImpact={
                      setImpact
                    }
                  />
                )
              )}
            </div>
          </section>

          <section className="high-impact-section">
            <div className="section-title-row">
              <div>
                <span className="section-kicker">
                  TRADE SETUP INPUT
                </span>

                <h2>
                  High-impact events
                </h2>
              </div>

              <span className="section-description">
                Predictions are shown separately
                from observed market outcomes.
              </span>
            </div>

            {highImpactItems.length ===
            0 ? (
              <div className="empty-intelligence">
                <strong>
                  No verified high-impact
                  events yet.
                </strong>

                <span>
                  New filings remain Not Sure
                  until MarketPulse classifies
                  and verifies their market impact.
                </span>
              </div>
            ) : (
              <div className="security-intelligence-list">
                {groupedSecurities.map((security) => (
                  <SecurityIntelligenceCard
                    key={
                      security.security_id ||
                      security.security_name
                    }
                    security={security}
                    onSelect={setSelectedItem}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="overall-ai-section">
            <div className="overall-ai-header">
              <div>
                <span className="section-kicker">
                  AI SYNTHESIS
                </span>

                <h3>
                  Overall AI Prediction
                </h3>
              </div>

              <span className="ai-status-badge">
                ON HOLD
              </span>
            </div>

            <div className="overall-ai-body">
              <strong>
                Overall AI prediction is currently
                disabled.
              </strong>

              <span>
                MarketPulse currently uses the
                LightGBM market-direction prediction
                for 1D, 5D and 10D horizons.
              </span>
            </div>
          </section>

          <section className="feed-section market-events-section">
            <div className="section-title-row">
              <div>
                <span className="section-kicker">MARKET EVENTS</span>
                <h2>Market event feed</h2>
              </div>
              <span className="section-description">
                Every feed remains available for AI prediction; price reaction needs a mapped security.
              </span>
            </div>

            <section className="feed-overview" aria-label="Market event overview">
              <div className="feed-overview-header">
                <div>
                  <span className="section-kicker">DATA COVERAGE</span>
                  <h3>Market event overview</h3>
                </div>
                <div className="latest-pulled">
                  <span>Latest data pulled</span>
                  <strong>{overviewLoading ? "Loading…" : formatDateTime(overview?.latest_data_pulled_at)}</strong>
                </div>
              </div>
              <div className="overview-table-wrap">
                <table className="overview-table">
                  <thead>
                    <tr>
                      <th>Total events</th>
                      <th>Equity</th>
                      <th>Mutual funds</th>
                      <th>ETF</th>
                      <th>Bonds</th>
                      <th>Others</th>
                      <th>Not mapped</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="overview-total">{overviewLoading ? "—" : (overview?.total_events ?? 0).toLocaleString("en-IN")}</td>
                      <td>{overviewLoading ? "—" : (overview?.equity_events ?? 0).toLocaleString("en-IN")}</td>
                      <td>{overviewLoading ? "—" : (overview?.mutual_fund_events ?? 0).toLocaleString("en-IN")}</td>
                      <td>{overviewLoading ? "—" : (overview?.etf_events ?? 0).toLocaleString("en-IN")}</td>
                      <td>{overviewLoading ? "—" : (overview?.bond_events ?? 0).toLocaleString("en-IN")}</td>
                      <td>{overviewLoading ? "—" : (overview?.other_events ?? 0).toLocaleString("en-IN")}</td>
                      <td>{overviewLoading ? "—" : (overview?.not_mapped_events ?? 0).toLocaleString("en-IN")}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div className="overview-meta">
                <span>Mapped: <strong>{overviewLoading ? "—" : (overview?.mapped_events ?? 0).toLocaleString("en-IN")}</strong></span>
                <span>Latest published: <strong>{overviewLoading ? "—" : formatDateTime(overview?.latest_published_at)}</strong></span>
              </div>
              {overviewError && (
                <div className="news-error">Market coverage: {overviewError}</div>
              )}
            </section>

            <div className="feed-tabs" role="tablist" aria-label="Market event feed">
              <button
                type="button"
                role="tab"
                aria-selected={feedTab === "EQUITY"}
                className={feedTab === "EQUITY" ? "active" : ""}
                onClick={() => setFeedTab("EQUITY")}
              >
                Equity market events
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={feedTab === "NON_EQUITY"}
                className={feedTab === "NON_EQUITY" ? "active" : ""}
                onClick={() => setFeedTab("NON_EQUITY")}
              >
                Mutual funds, ETF, bonds & others
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={feedTab === "EXCEPTIONS"}
                className={feedTab === "EXCEPTIONS" ? "active" : ""}
                onClick={() => setFeedTab("EXCEPTIONS")}
              >
                Not classified or not mapped
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={feedTab === "PIPELINE"}
                className={feedTab === "PIPELINE" ? "active" : ""}
                onClick={() => setFeedTab("PIPELINE")}
              >
                Pipeline / Coverage
              </button>
            </div>

            {feedTab !== "PIPELINE" && (
            <div className="intelligence-toolbar">
              <div className="search-wrap">
                <span aria-hidden="true">⌕</span>
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search stock, company, ISIN, BSE scrip code, symbol or announcement"
                  aria-label="Search market events"
                />
                {search && (
                  <button
                    type="button"
                    className="search-clear"
                    onClick={() => setSearch("")}
                    aria-label="Clear search"
                  >
                    ×
                  </button>
                )}
              </div>

              <div className="filter-group">
                {["ALL", "NSE", "BSE"].map((value) => (
                  <button
                    type="button"
                    key={value}
                    className={exchange === value ? "active" : ""}
                    onClick={() => setExchange(value)}
                  >
                    {value === "ALL" ? "All Exchanges" : value}
                  </button>
                ))}
              </div>

              <select
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                aria-label="Filter event category"
              >
                <option value="ALL">All Categories</option>
                {CATEGORY_CONFIG.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>

              <select
                value={assetCategory}
                onChange={(event) => setAssetCategory(event.target.value)}
                aria-label="Filter asset type"
              >
                {ASSET_CATEGORY_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value === "ALL"
                      ? "All Asset Types"
                      : value === "UNCLASSIFIED"
                      ? "Not Classified"
                      : value}
                  </option>
                ))}
              </select>

              <span className="result-count">
                {total} events
              </span>
            </div>

            )}

            <div className="feed-tab-panel">
              {feedTab === "EQUITY" && (
                <div className="security-intelligence-list">
                  {groupedFeedItems.map((security) => (
                    <SecurityIntelligenceCard
                      key={security.security_id || `${security.security_name}-${security.asset_category}`}
                      security={security}
                      onSelect={setSelectedItem}
                      onHistory={setSelectedHistoryGroup}
                    />
                  ))}
                  {groupedFeedItems.length === 0 && (
                    <div className="empty-intelligence">
                      <strong>No equity securities match the current filters.</strong>
                      <span>Try another stock, ISIN, exchange or search term.</span>
                    </div>
                  )}
                </div>
              )}

              {feedTab === "NON_EQUITY" && (
                <div className="security-intelligence-list">
                  {groupedFeedItems.map((security) => (
                    <SecurityIntelligenceCard
                      key={security.security_id || `${security.security_name}-${security.asset_category}`}
                      security={security}
                      onSelect={setSelectedItem}
                      onHistory={setSelectedHistoryGroup}
                    />
                  ))}
                  {groupedFeedItems.length === 0 && (
                    <div className="empty-intelligence">
                      <strong>No mutual fund, ETF, bond or other groups match the current filters.</strong>
                      <span>Try another asset type or search term.</span>
                    </div>
                  )}
                </div>
              )}

              {feedTab === "EXCEPTIONS" && (
                <>
                  <section className="mapping-control-card">
                    <div>
                      <span className="section-kicker">MAPPING CONTROL</span>
                      <h3>Map unresolved events</h3>
                      <p>
                        Review deterministic name/symbol candidates and Mapping Agent decisions before applying them to security_master.
                      </p>
                    </div>
                    <div className="mapping-control-actions">
                      <button type="button" onClick={openMapper}>Open Mapper →</button>
                      <button type="button" className="secondary" onClick={refreshCurrentFeed}>Refresh</button>
                    </div>
                  </section>

                  <div className="feed-table unresolved-feed-table">
                    {paginatedItems.map((item) => (
                        <NewsRow
                          key={item.news_id}
                          item={item}
                          onSelect={setSelectedItem}
                        />
                      ))}

                    {paginatedItems.length === 0 && (
                      <div className="empty-intelligence">
                        <strong>No unclassified or unmapped records.</strong>
                        <span>Mapped records stay out of this exceptions view.</span>
                      </div>
                    )}
                  </div>
                </>
              )}
              {feedTab === "PIPELINE" && (
                pipelineOverviewError ? (
                  <div className="news-error">Pipeline coverage: {pipelineOverviewError}</div>
                ) : (
                  <PipelineDashboard
                    data={pipelineOverviewLoading ? null : pipelineOverview}
                    onOpenExceptions={() => setFeedTab("EXCEPTIONS")}
                  />
                )
              )}
            </div>

            {feedTab !== "PIPELINE" && pageCount > 1 && (
              <div className="pagination">
                <button
                  type="button"
                  disabled={page === 1}
                  onClick={() => setPage((value) => value - 1)}
                >
                  ← Previous
                </button>
                <span>
                  Page <strong>{page}</strong> of <strong>{pageCount}</strong>
                </span>
                <button
                  type="button"
                  disabled={page === pageCount}
                  onClick={() => setPage((value) => value + 1)}
                >
                  Next →
                </button>
              </div>
            )}
          </section>
        </>
      )}

      {mapperOpen && (
        <div
          className="news-detail-overlay"
          onClick={() => setMapperOpen(false)}
        >
          <aside
            className="news-detail-panel"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="detail-top">
              <div>
                <span className="section-kicker">MAPPING CONTROL</span>
                <h2>Security Mapper</h2>
                <p className="detail-description">
                  Run the canonical deterministic mapper for one unresolved event at a time. This control does not start a long-running 50K-event database update.
                </p>
              </div>

              <button
                type="button"
                className="close-detail"
                onClick={() => setMapperOpen(false)}
                aria-label="Close"
              >
                ×
              </button>
            </div>

            <div className="detail-analysis-grid">
              <div>
                <span>Scope</span>
                <strong>Unmapped events</strong>
              </div>
              <div>
                <span>Deterministic mapper</span>
                <strong>READY</strong>
              </div>
              <div>
                <span>Mapping Agent</span>
                <strong>READY</strong>
              </div>
              <div>
                <span>Execution</span>
                <strong>Targeted event</strong>
              </div>
            </div>

            {mapperControlError && (
              <div className="news-error">
                {mapperControlError}
              </div>
            )}

            <div className="detail-section-heading">
              <div>
                <span>UNMAPPED EVENTS</span>
                <h3>Run security mapper</h3>
              </div>
              <small>Current exceptions page</small>
            </div>

            <div className="mapper-control-list">
              {paginatedItems.filter((eventItem) => !isMapped(eventItem)).map((eventItem) => (
                <div
                  key={eventItem.news_id}
                  className="mapper-control-row"
                >
                  <div className="mapper-control-event">
                    <strong>
                      {eventItem.company_name ||
                        eventItem.title ||
                        "Unresolved event"}
                    </strong>
                    <span>
                      News ID {eventItem.news_id}
                      {eventItem.exchange ? ` · ${eventItem.exchange}` : ""}
                    </span>
                    <small>
                      {truncate(
                        eventItem.title ||
                          eventItem.description ||
                          "No event title available.",
                        110
                      )}
                    </small>
                  </div>

                  <button
                    type="button"
                    className="mapper-run-button"
                    onClick={() => runMapperFromControl(eventItem)}
                    disabled={mapperRunningId !== null}
                  >
                    {mapperRunningId === eventItem.news_id
                      ? "Mapping…"
                      : "Run Mapper"}
                  </button>
                </div>
              ))}

              {paginatedItems.filter((eventItem) => !isMapped(eventItem)).length === 0 && (
                <div className="actual-pending">
                  No unresolved events are present on the current page.
                </div>
              )}
            </div>

            <div className="actual-pending">
              After a successful mapping, open the event details and use the existing LightGBM score action.
            </div>
          </aside>
        </div>
      )}

      <HistoryPanel
        security={selectedHistoryGroup}
        onClose={() => setSelectedHistoryGroup(null)}
        onSelect={setSelectedItem}
      />

      <DetailPanel
        item={selectedItem}
        agentFeedback={selectedItem ? agentFeedback[selectedItem.news_id] : null}
        onAgentFeedback={handleAgentFeedback}
        onMapped={handleMapped}
        onScored={handleScored}
        onClose={() =>
          setSelectedItem(null)
        }
      />
    </div>
  );
}