# Deploying PC Optimizer to Render

## Quick Setup (5 minutes)

### Step 1: Sign Up
1. Go to: https://render.com
2. Click "Get Started" → Sign in with **GitHub**
3. Authorize access to your repos

### Step 2: Create Web Service
1. In Render dashboard, click **"New +"** → **"Web Service"**
2. Find your repo: `ruddyribera-ops/pc-optimizer-ai`
3. Click **"Connect"**

### Step 3: Configure
```
Name: pc-optimizer-ai
Environment: Python
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

### Step 4: Deploy
- Select **Free** tier (free!)
- Click **"Create Web Service"**

## After Deploy

Your app will be live at: `https://pc-optimizer-ai.onrender.com`

## Update the Dashboard

Edit `templates/index.html` and change the API_URL to your new Render URL.

## Troubleshooting

**If build fails:**
- Make sure `runtime.txt` exists with: `python-3.12`

Let me know when you're done or if you hit any issues!