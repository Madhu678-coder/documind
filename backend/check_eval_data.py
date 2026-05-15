#!/usr/bin/env python3
"""
Diagnostic script to check evaluation data in the database.
Run this to see if evaluations are actually being stored and what data they contain.
"""
import asyncio
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models.eval_result import EvalResult
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession


async def check_eval_data():
    """Check what evaluation data exists in the database."""
    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print("EVALUATION DATA DIAGNOSTIC")
        print("=" * 80)
        
        # Count total eval results
        result = await db.execute(select(func.count(EvalResult.id)))
        total_evals = result.scalar_one()
        print(f"\n✓ Total evaluation results: {total_evals}")
        
        if total_evals == 0:
            print("\n❌ NO EVALUATION DATA FOUND!")
            print("\nPossible reasons:")
            print("1. Celery eval worker is not running")
            print("2. No chat messages have been sent yet")
            print("3. Evaluations are failing silently")
            print("\nTo fix:")
            print("  1. Start Celery worker: celery -A app.workers worker -Q eval_queue --loglevel=info")
            print("  2. Send some chat messages")
            print("  3. Check worker logs for errors")
            return
        
        # Check for neutral scores (indicates evaluation not actually running)
        result = await db.execute(
            select(func.count(EvalResult.id))
            .where(
                EvalResult.faithfulness_score == 1.0,
                EvalResult.answer_relevancy_score == 1.0,
                EvalResult.contextual_precision_score == 1.0,
                EvalResult.contextual_recall_score == 1.0,
                EvalResult.hallucination_score == 0.0,
            )
        )
        neutral_count = result.scalar_one()
        
        if neutral_count == total_evals:
            print(f"\n⚠️  WARNING: All {neutral_count} evaluations have NEUTRAL SCORES!")
            print("\nThis means evaluations are being triggered but not actually running.")
            print("\nPossible reasons:")
            print("1. DeepEval is not installed: pip install deepeval>=1.0.0")
            print("2. AWS Bedrock credentials not configured")
            print("3. DeepEval metrics are failing and falling back to neutral scores")
            print("\nCheck Celery worker logs for errors like:")
            print("  - 'deepeval not installed'")
            print("  - 'DeepEval evaluation error'")
            print("  - AWS credential errors")
        elif neutral_count > 0:
            print(f"\n⚠️  WARNING: {neutral_count}/{total_evals} evaluations have neutral scores")
            print("Some evaluations are working, but some are failing.")
        else:
            print(f"\n✓ All {total_evals} evaluations have real scores (not neutral)")
        
        # Show sample of recent evaluations
        print("\n" + "=" * 80)
        print("RECENT EVALUATIONS (last 5)")
        print("=" * 80)
        
        result = await db.execute(
            select(EvalResult, ChatMessage)
            .join(ChatMessage, EvalResult.message_id == ChatMessage.id)
            .order_by(EvalResult.evaluated_at.desc())
            .limit(5)
        )
        rows = result.all()
        
        if not rows:
            print("No evaluations found.")
        else:
            for eval_result, message in rows:
                print(f"\nMessage ID: {eval_result.message_id}")
                print(f"Evaluated: {eval_result.evaluated_at}")
                print(f"Triggered by: {eval_result.triggered_by}")
                print(f"Scores:")
                print(f"  - Faithfulness: {eval_result.faithfulness_score:.3f}")
                print(f"  - Answer Relevancy: {eval_result.answer_relevancy_score:.3f}")
                print(f"  - Contextual Precision: {eval_result.contextual_precision_score:.3f}")
                print(f"  - Contextual Recall: {eval_result.contextual_recall_score:.3f}")
                print(f"  - Hallucination: {eval_result.hallucination_score:.3f}")
                print(f"  - Overall Pass: {eval_result.overall_pass}")
                print(f"Message preview: {message.content[:100]}...")
                
                # Check if neutral
                is_neutral = (
                    eval_result.faithfulness_score == 1.0 and
                    eval_result.answer_relevancy_score == 1.0 and
                    eval_result.contextual_precision_score == 1.0 and
                    eval_result.contextual_recall_score == 1.0 and
                    eval_result.hallucination_score == 0.0
                )
                if is_neutral:
                    print("  ⚠️  NEUTRAL SCORES - evaluation not actually running!")
        
        # Count chat messages vs evaluations
        print("\n" + "=" * 80)
        print("COVERAGE CHECK")
        print("=" * 80)
        
        result = await db.execute(
            select(func.count(ChatMessage.id))
            .where(ChatMessage.role == "assistant")
        )
        total_assistant_msgs = result.scalar_one()
        
        coverage_pct = (total_evals / total_assistant_msgs * 100) if total_assistant_msgs > 0 else 0
        print(f"\nAssistant messages: {total_assistant_msgs}")
        print(f"Evaluations: {total_evals}")
        print(f"Coverage: {coverage_pct:.1f}%")
        
        if coverage_pct < 100:
            print(f"\n⚠️  {total_assistant_msgs - total_evals} messages are missing evaluations")
            print("This is normal if messages were sent before the eval worker was started.")
        
        # Check for recent messages without evaluations
        result = await db.execute(
            select(ChatMessage)
            .outerjoin(EvalResult, EvalResult.message_id == ChatMessage.id)
            .where(
                ChatMessage.role == "assistant",
                EvalResult.id.is_(None)
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(5)
        )
        unevaluated = result.scalars().all()
        
        if unevaluated:
            print(f"\n⚠️  Recent messages without evaluations:")
            for msg in unevaluated:
                print(f"  - {msg.id} (created: {msg.created_at})")
        
        print("\n" + "=" * 80)
        print("RECOMMENDATIONS")
        print("=" * 80)
        
        if total_evals == 0:
            print("\n1. Start the Celery eval worker")
            print("2. Send chat messages to generate evaluations")
        elif neutral_count == total_evals:
            print("\n1. Install DeepEval: pip install deepeval>=1.0.0")
            print("2. Configure AWS credentials for Bedrock")
            print("3. Restart Celery worker")
            print("4. Send new chat messages")
            print("5. Check worker logs for errors")
        elif neutral_count > 0:
            print("\n1. Check Celery worker logs for intermittent errors")
            print("2. Verify AWS Bedrock rate limits")
        else:
            print("\n✓ Evaluations are working correctly!")
            print("✓ Real data should be visible in the Settings page")
            print("\nIf you still see sample data in the UI:")
            print("1. Refresh the Settings page")
            print("2. Check browser console for API errors")
            print("3. Verify you're logged in as an admin user")


if __name__ == "__main__":
    asyncio.run(check_eval_data())
