"""Seed admin user for DocuMind."""
import asyncio
import bcrypt
import uuid
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from sqlalchemy import select

ADMIN_EMAIL = "admin@documind.ai"
ADMIN_PASSWORD = "Admin123!"
ADMIN_NAME = "Admin User"


async def seed_admin():
    """Create admin user if it doesn't exist."""
    async with AsyncSessionLocal() as db:
        # Check if admin user already exists
        result = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            print(f"✅ Admin user already exists: {ADMIN_EMAIL}")
            return
        
        # Step 1: Create user without workspace (workspace_id is now nullable)
        hashed_password = bcrypt.hashpw(ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        admin_user = User(
            email=ADMIN_EMAIL,
            hashed_password=hashed_password,
            name=ADMIN_NAME,
            role="admin"
        )
        db.add(admin_user)
        await db.flush()  # Get user ID
        
        # Step 2: Create workspace with admin as owner
        workspace = Workspace(
            name="Default Workspace",
            owner_id=admin_user.id,
            settings={}
        )
        db.add(workspace)
        await db.flush()  # Get workspace ID
        
        # Step 3: Update user with workspace_id
        admin_user.workspace_id = workspace.id
        
        await db.commit()
        
        print(f"✅ Admin user created successfully!")
        print(f"   Email: {ADMIN_EMAIL}")
        print(f"   Password: {ADMIN_PASSWORD}")
        print(f"   Workspace: {workspace.name}")
        print(f"   User ID: {admin_user.id}")
        print(f"   Workspace ID: {workspace.id}")


if __name__ == "__main__":
    asyncio.run(seed_admin())
