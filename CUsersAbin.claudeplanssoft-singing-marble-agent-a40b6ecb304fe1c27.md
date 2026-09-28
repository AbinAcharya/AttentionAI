# Implementation Plan: Polish AttentionAI UI

## Goals
1. **Remove 'Stickiness'** (Eliminate full-screen re-compositions and improve fluid animations).
2. **Update Colors** (Replace  with a cohesive blue palette).
3. **Enhance 'Feel'** (Smooth out state transitions for switches and chips).

## 1. Remove Stickiness

### A. Fix  Re-compositions
Currently,  uses a  state that triggers a full re-read of  and  on every update, causing the entire  to re-compose.

- **Problem**:  in  causes the  function to be called again with new parameters every time  changes.
- **Solution**: Move the state reading into a  or use a  with . For a lightweight fix:
    - Use  or  for the system state.
    - Decouple  and  so they don't both trigger on the same tick if not necessary.
    - Ensure  is computed on a background thread using .

### B. Fluid List Updates
The  in  lacks item animations.

- **Action**: Add  (formerly ) to the  blocks in .
- **Files**:  (lines 106-137).

### C. State Transition Animations
Improve the Setup $\to$ Active transition.
- **Action**: Ensure  in  (lines 116-123) is configured with a smooth transition. The current  is a good start, but we can refine the  to use a  for a more iOS-like feel.

## 2. Update Colors

### A. Blue Palette Definition
Replace  () with a blue variant. Since  () is already present, we'll use a consistent palette:
- **Primary Blue**:  ()
- **Light Blue (for backgrounds)**:  or  (if light mode, but we are in dark mode).

### B. Application of Colors
- **Priority Chips**: In , change  to  for the 'Always' tier.
- **Unmute Button**: In  (line 415), change  to  when the user is muted.
- **Recent Activity**: In  (line 334), change  color from  to .

## 3. Enhance Feel

### A. Switch & FilterChip Polish
- **Switch**: Ensure  uses the updated blue palette.
- **FilterChip**: Ensure  and  use the updated blue palette with smooth transitions via .

## Step-by-Step Implementation Strategy

### Step 1: Architecture Fix (MainActivity.kt)
1. Replace  with a more granular state management approach.
2. Wrap  and  in a way that they don't block the main thread.
3. Suggestion: Create a  to hold  and  as s.

### Step 2: UI Color Update (HomeScreen.kt)
1. Update the color constants.
2. Find all references to  and replace them with  (or a specific variant for 'Always' priority).
3. Review  and  for color consistency.

### Step 3: Animation & Fluidity (HomeScreen.kt)
1. Add  to  items.
2. Refine  transitions for  and .
3. Verify that  is used consistently for all color transitions.

## Critical Files for Implementation
- 
- 

