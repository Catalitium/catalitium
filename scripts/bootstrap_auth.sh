#!/usr/bin/env bash
# Bootstrap Supabase Auth dependency
# Run this BEFORE pasting the Cursor prompt
set -e

echo "Installing supabase-py..."
pip install supabase==2.10.0

echo "Verifying import..."
python -c "from supabase import create_client; print('supabase-py OK')"

echo ""
echo "Next steps:"
echo "  1. Add SUPABASE_PROJECT_URL=https://<ref>.supabase.co to .env"
echo "  2. Confirm SUPABASE_SECRET_KEY in .env is the service_role key"
echo "  3. In Supabase Dashboard > Auth > URL Config: add http://localhost:5000"
echo "  4. Paste the prompt from tasks/todo.md into Cursor Composer"
