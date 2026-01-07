# TouchDesigner Component Setup Guide

This guide shows you how to create the ComfyUI Client component in TouchDesigner. Once created, you can save it as a `.tox` file and share it with anyone!

## Quick Overview

The component will look like this when done:

```
┌─ comfy_client (Base COMP) ─────────────────────────┐
│                                                     │
│  Parameters Panel:                                  │
│  ┌─ Comfy ────────────────────────────────────┐    │
│  │ Server URL: [https://...trycloudflare.com] │    │
│  │ Prompt:     [________________________]     │    │
│  │ Source TOP: [source_top             ▼]     │    │
│  │ Poll Interval: [15]                        │    │
│  │ Active: [ ] (toggle)                       │    │
│  └────────────────────────────────────────────┘    │
│  ┌─ Status ───────────────────────────────────┐    │
│  │ Job ID:     abc12345                       │    │
│  │ Job Status: processing                     │    │
│  │ Last Result: C:\temp\td_comfy_result.mp4   │    │
│  └────────────────────────────────────────────┘    │
│                                                     │
│  Inside the component:                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐     │
│  │ script   │  │ execute  │  │ output       │     │
│  │ (TextDAT)│→ │(ExecDAT) │  │(MovieFileIn) │     │
│  └──────────┘  └──────────┘  └──────────────┘     │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## Step-by-Step Setup

### Step 1: Create the Base Component

1. In TouchDesigner, **right-click** in the Network Editor
2. Select **COMP** → **Base**
3. A new Base COMP appears
4. **Rename** it to `comfy_client` (press `N` to rename, or right-click → Rename)

### Step 2: Add Custom Parameters

1. **Right-click** the `comfy_client` Base COMP
2. Select **Customize Component...**
3. The Component Editor window opens

#### Create "Comfy" Page:

1. Click **+ (Add Page)** at the bottom
2. Name it `Comfy`
3. Add these parameters (click **+ Add Parameter** for each):

| Label | Name | Type | Default Value |
|-------|------|------|---------------|
| Server URL | Serverurl | String | `https://beach-restructuring-penn-tvs.trycloudflare.com` |
| Prompt | Prompt | String | (leave empty) |
| Source TOP | Sourcetop | TOP | (leave empty) |
| Poll Interval | Pollinterval | Int | `15` |
| Active | Active | Toggle | Off |

#### Create "Status" Page:

1. Click **+ (Add Page)** at the bottom  
2. Name it `Status`
3. Add these parameters:

| Label | Name | Type | Default Value |
|-------|------|------|---------------|
| Job ID | Jobid | String | (leave empty) |
| Job Status | Jobstatus | String | `idle` |
| Last Result | Lastresult | String | (leave empty) |

4. Click **Apply** and close the Component Editor

### Step 3: Go Inside the Component

1. **Double-click** the `comfy_client` Base COMP to enter it
2. You're now inside the component's network

### Step 4: Create the Script DAT

1. **Right-click** → **DAT** → **Text**
2. Rename it to `script`
3. **Open** the file `comfy_client_comp.py` in a text editor
4. **Copy** all the code
5. In TouchDesigner, click on the `script` DAT
6. In the **Text Editor** panel, **paste** the code
7. Press **Ctrl+S** to save (or click Apply)

### Step 5: Create the Execute DAT

1. **Right-click** → **DAT** → **Execute**
2. Rename it to `execute`
3. In the parameters panel:
   - Set **DAT** to `script` (drag the script DAT here, or type `script`)
   - Set **Run** to `On` (toggle it on!)
   - Make sure **Defer** is `Off`

### Step 6: Create the Output TOP

1. **Right-click** → **TOP** → **Movie File In**
2. Rename it to `output`
3. This TOP will automatically play the result videos

### Step 7: Navigate Back Out

1. Press **U** or click the **up arrow** to go back to the parent network
2. You should see your `comfy_client` Base COMP

---

## Using the Component

### Connect Your Source

1. Create any TOP as your video source (Movie File In, Video Device In, NDI In, etc.)
2. Name it something like `source_top`
3. On the `comfy_client` component, find **Source TOP** parameter
4. Drag your source TOP onto this parameter (or type its name)

### Configure the Server

1. Get the server URL from the person running the ComfyUI server
2. Enter it in the **Server URL** parameter
3. Example: `https://beach-restructuring-penn-tvs.trycloudflare.com`

### Start Processing

1. Toggle **Active** to **On**
2. The component will:
   - Capture a frame from your source
   - Send it to the server
   - Wait for the AI to process it
   - Download and play the result video
   - Automatically send the next frame

### View the Output

- The result video plays inside the component in the `output` TOP
- You can wire this to other operators by clicking the output TOP and dragging a wire from it

---

## Saving as .tox (For Sharing)

Once your component is set up and working:

1. **Right-click** the `comfy_client` Base COMP
2. Select **Save Component .tox...**
3. Save it as `comfy_client.tox`

**To use the .tox:**
- Just drag and drop `comfy_client.tox` into any TouchDesigner project!
- All the parameters and script are included

---

## Troubleshooting

### "error: no url"
- The Server URL parameter is empty. Enter the server address.

### "error: no source"
- No source TOP is selected. Drag your video source to the Source TOP parameter.

### "unreachable" or connection errors
- Check that the server is running
- Verify the URL is correct (should start with https://)
- Check your internet connection

### Video doesn't play
- Check the `output` TOP inside the component
- Make sure the workflow on the server completed successfully
- Check the server's `/health` endpoint

### Stuck on "processing"
- The AI workflow is still running
- LTXV video generation takes 30-60+ seconds
- Check ComfyUI on the server for progress

---

## Network Diagram

```
YOUR TD PROJECT
================

┌──────────────┐
│ source_top   │  (Your video input - camera, video, NDI, etc.)
│ (any TOP)    │
└──────┬───────┘
       │
       │  (wire or reference via parameter)
       ▼
┌──────────────────────────────────────────────────────────┐
│ comfy_client (Base COMP)                                 │
│                                                          │
│   Parameters:                                            │
│   - Server URL: https://xxx.trycloudflare.com           │
│   - Prompt: (optional text)                              │
│   - Source TOP: source_top                               │
│   - Active: ON                                           │
│                                                          │
│   ┌─────────────────────────────────────────────────┐   │
│   │ Inside:                                          │   │
│   │  script (Text DAT) → execute (Execute DAT)       │   │
│   │                         │                        │   │
│   │                         ▼                        │   │
│   │                    output (Movie File In TOP)    │   │
│   └─────────────────────────────────────────────────┘   │
│                                                          │
└─────────────────────────┬────────────────────────────────┘
                          │
                          │  (the output TOP inside)
                          ▼
              ┌──────────────────────┐
              │ Use anywhere in your │
              │ project!             │
              └──────────────────────┘
```

---

## Questions?

Check the server's API docs at:
`https://YOUR_SERVER_URL/docs`

This shows all available endpoints and lets you test the API directly.