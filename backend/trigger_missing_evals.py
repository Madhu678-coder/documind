#!/usr/bin/env python3
"""
Trigger evaluations for existing assistant messages that don't have evaluations yet.
Run this after starting the eval worker to backfill missing evaluations.
"""
import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.eval_result import EvalResult
from app.workers.eval_tasks import evaluate_response_async


async def trigger_missing_evaluations():
    """Find assistant messages without evaluations and trigger them."""
    async with AsyncSessionLocal() as db:
        # Find assistant messages without evaluations
        result = await db.execute(
            select(ChatMessage, ChatSession)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .outerjoin(EvalResult, EvalResult.message_id == ChatMessage.id)
            .where(
                ChatMessage.role == "assistant",
                EvalResult.id.is_(None)
            )
            .order_by(ChatMessage.created_at)
        )
        rows = result.all()
        
        if not rows:
            print("✓ All assistant messages already have evaluations!")
            return
        
        print(f"Found {len(rows)} assistant messages without evaluations")
        print("Triggering evaluation tasks...\n")
        
        for message, session in rows:
            print(f"Triggering evaluation for message {message.id}")
            print(f"  Session: {session.id}")
            print(f"  Created: {message.created_at}")
            print(f"  Content preview: {message.content[:80]}...")
            
            # Trigger async evaluation task
            evaluate_response_async.apply_async(
                args=[str(message.id), str(session.workspace_id)],
                kwargs={"triggered_by": "backfill"},
            )
            print("  ✓ Task queued\n")
        
        print(f"\n✓ Queued {len(rows)} evaluation tasks")
        print("\nNext steps:")
        print("1. Make sure eval worker is running: ./start_eval_worker.sh")
        print("2. Wait 30-60 seconds for evaluations to complete")
        print("3. Run: python3 check_eval_data.py")
        print("4. Refresh Settings page in browser")


if __name__ == "__main__":
    asyncio.run(trigger_missing_evaluations())
