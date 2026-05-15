-- Quick SQL queries to check evaluation data
-- Run these in your PostgreSQL client to diagnose issues

-- 1. Count total evaluations
SELECT COUNT(*) as total_evaluations FROM eval_results;

-- 2. Count evaluations with neutral scores (indicates eval not actually running)
SELECT COUNT(*) as neutral_score_count 
FROM eval_results 
WHERE faithfulness_score = 1.0 
  AND answer_relevancy_score = 1.0 
  AND contextual_precision_score = 1.0 
  AND contextual_recall_score = 1.0 
  AND hallucination_score = 0.0;

-- 3. Show recent evaluations with scores
SELECT 
    message_id,
    evaluated_at,
    triggered_by,
    faithfulness_score,
    answer_relevancy_score,
    contextual_precision_score,
    contextual_recall_score,
    hallucination_score,
    overall_pass
FROM eval_results 
ORDER BY evaluated_at DESC 
LIMIT 10;

-- 4. Count assistant messages vs evaluations (coverage check)
SELECT 
    (SELECT COUNT(*) FROM chat_messages WHERE role = 'assistant') as assistant_messages,
    (SELECT COUNT(*) FROM eval_results) as evaluations,
    ROUND(
        (SELECT COUNT(*)::numeric FROM eval_results) / 
        NULLIF((SELECT COUNT(*) FROM chat_messages WHERE role = 'assistant'), 0) * 100, 
        1
    ) as coverage_percent;

-- 5. Find messages without evaluations
SELECT 
    cm.id,
    cm.created_at,
    LEFT(cm.content, 100) as content_preview
FROM chat_messages cm
LEFT JOIN eval_results er ON er.message_id = cm.id
WHERE cm.role = 'assistant' 
  AND er.id IS NULL
ORDER BY cm.created_at DESC
LIMIT 10;

-- 6. Check score distribution (should vary if real evaluations)
SELECT 
    ROUND(faithfulness_score::numeric, 1) as faithfulness_bucket,
    COUNT(*) as count
FROM eval_results
GROUP BY ROUND(faithfulness_score::numeric, 1)
ORDER BY faithfulness_bucket;

-- 7. Check if all scores are identical (bad sign)
SELECT 
    faithfulness_score,
    answer_relevancy_score,
    contextual_precision_score,
    contextual_recall_score,
    hallucination_score,
    COUNT(*) as count
FROM eval_results
GROUP BY 
    faithfulness_score,
    answer_relevancy_score,
    contextual_precision_score,
    contextual_recall_score,
    hallucination_score
ORDER BY count DESC;
