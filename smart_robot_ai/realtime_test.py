import os
import time
from collections import deque
import cv2
import numpy as np
import tensorflow as tf

# =========================================================
# CONFIGURATION
# =========================================================

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")
MODEL_PATH = os.path.join(MODEL_DIR, "smart_robot_model.h5")

# 5 classes including "none" for negative samples (no valid sign)
CLASS_NAMES = ["go", "stop", "left", "right", "none"]

IMAGE_SIZE = (64, 64)

# CONFIDENCE THRESHOLD RATIONALE:
# ==============================
# Predictions below 0.75 confidence are considered unreliable.
# Instead of guessing, we output "none" to indicate "no valid sign detected".
# This prevents false positive commands that could cause safety issues.
# Threshold of 0.75 provides good balance:
#   - Avoids false positives on random objects
#   - Captures genuine sign detections with good certainty
#   - Works well on Raspberry Pi with limited compute
CONFIDENCE_THRESHOLD = 0.75

# TEMPORAL SMOOTHING CONFIGURATION:
# =================================
# WHY TEMPORAL SMOOTHING MATTERS FOR ROBOTICS:
# 1. Stabilizes flickering predictions (prevents rapid switching)
# 2. Filters out single-frame noise and artifacts
# 3. Makes robot behavior more predictable and safer
# 4. Improves robustness on edge cases (partial signs, blur)
#
# METHOD: Majority voting on last N predictions
# - Window size: 5 frames (good balance between responsiveness and stability)
# - Voting: Take the most common prediction in the window
# - Result: Smooth, stable predictions without lag
TEMPORAL_WINDOW_SIZE = 5


# =========================================================
# MODEL LOADING
# =========================================================

def load_model():
    """Load the trained Keras model."""
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Trained model not found at {MODEL_PATH}. Run train_model.py first.")
    return tf.keras.models.load_model(MODEL_PATH)


# =========================================================
# PREPROCESSING
# =========================================================

def preprocess_frame(frame):
    """
    Preprocess frame for model inference.
    
    Steps:
    1. Resize to 64x64 (lightweight for Raspberry Pi)
    2. Convert BGR to RGB (match training format)
    3. Normalize to [0, 1] (match training normalization)
    4. Add batch dimension for model input
    """
    image = cv2.resize(frame, IMAGE_SIZE)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image = image.astype(np.float32) / 255.0
    return np.expand_dims(image, axis=0)


# =========================================================
# PREDICTION & CONFIDENCE
# =========================================================

def predict_with_confidence(model, frame):
    """
    Get prediction and confidence from model.
    
    Returns:
        tuple: (predicted_class, confidence_score, all_scores)
    """
    input_tensor = preprocess_frame(frame)
    predictions = model.predict(input_tensor, verbose=0)
    
    confidence = float(np.max(predictions))
    class_index = int(np.argmax(predictions))
    
    return class_index, confidence, predictions[0]


def get_final_prediction(class_index, confidence):
    """
    Apply confidence threshold to get final prediction.
    
    Logic:
    - If confidence >= CONFIDENCE_THRESHOLD: Use predicted class
    - If confidence < CONFIDENCE_THRESHOLD: Output "none" (no sign)
    
    This prevents false positives on random objects.
    """
    if confidence >= CONFIDENCE_THRESHOLD:
        return CLASS_NAMES[class_index]
    else:
        # Low confidence → "none" (no valid sign detected)
        return "none"


# =========================================================
# TEMPORAL SMOOTHING
# =========================================================

class PredictionSmoother:
    """
    Stabilize predictions using temporal smoothing.
    
    Strategy: Majority voting on last N predictions
    Benefits:
    - Eliminates single-frame noise
    - Prevents flickering between classes
    - Makes robot behavior smooth and predictable
    - Especially important for partial signs and blur
    """
    
    def __init__(self, window_size=TEMPORAL_WINDOW_SIZE):
        self.window_size = window_size
        self.prediction_history = deque(maxlen=window_size)
    
    def add_prediction(self, prediction):
        """Add new prediction to history."""
        self.prediction_history.append(prediction)
    
    def get_smoothed_prediction(self):
        """
        Get majority voted prediction from history.
        
        Returns:
            str: Most common prediction in the window
                 Returns "none" if window is empty
        """
        if len(self.prediction_history) == 0:
            return "none"
        
        # Count occurrences of each prediction
        from collections import Counter
        counts = Counter(self.prediction_history)
        
        # Return most common (majority vote)
        return counts.most_common(1)[0][0]


# =========================================================
# VISUALIZATION
# =========================================================

def get_text_color(prediction):
    """
    Get BGR color for prediction text based on class.
    
    Colors:
    - Green (0, 255, 0) for "go"
    - Red (0, 0, 255) for "stop"
    - Blue (255, 0, 0) for "left"
    - Cyan (255, 255, 0) for "right"
    - Gray (200, 200, 200) for "none" (no sign)
    """
    color_map = {
        "go": (0, 255, 0),      # Green
        "stop": (0, 0, 255),    # Red
        "left": (255, 0, 0),    # Blue
        "right": (255, 255, 0), # Cyan
        "none": (200, 200, 200) # Gray
    }
    return color_map.get(prediction, (200, 200, 200))


def draw_overlay(frame, raw_prediction, smoothed_prediction, confidence, fps):
    """
    Draw comprehensive overlay on frame.
    
    Displays:
    1. Raw neural network prediction
    2. Smoothed prediction (after temporal filtering)
    3. Confidence percentage
    4. FPS counter
    5. Status indicators
    """
    height = frame.shape[0]
    width = frame.shape[1]
    
    # Dark background panel
    cv2.rectangle(frame, (0, 0), (width, 150), (0, 0, 0), -1)
    
    # Raw prediction
    cv2.putText(
        frame,
        f"Raw: {raw_prediction}",
        (10, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        get_text_color(raw_prediction),
        2
    )
    
    # Smoothed prediction (larger font, emphasize stability)
    smoothed_color = get_text_color(smoothed_prediction)
    cv2.putText(
        frame,
        f"Smoothed: {smoothed_prediction.upper()}",
        (10, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        smoothed_color,
        3
    )
    
    # Confidence percentage
    confidence_text = f"Confidence: {confidence * 100:.1f}%"
    confidence_color = (0, 255, 0) if confidence >= CONFIDENCE_THRESHOLD else (0, 165, 255)
    cv2.putText(
        frame,
        confidence_text,
        (10, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        confidence_color,
        2
    )
    
    # FPS counter (performance monitoring for Raspberry Pi)
    cv2.putText(
        frame,
        f"FPS: {fps:.1f}",
        (width - 150, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (200, 200, 200),
        2
    )


# =========================================================
# MAIN INFERENCE LOOP
# =========================================================

def main():
    """
    Main realtime inference loop.
    
    Workflow:
    1. Load trained model
    2. Initialize webcam
    3. For each frame:
       a. Preprocess and get raw prediction
       b. Apply confidence threshold
       c. Apply temporal smoothing (majority voting)
       d. Draw overlay with all information
       e. Display and handle user input
    """
    try:
        model = load_model()
    except FileNotFoundError as error:
        print(error)
        return

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open the webcam.")
        return

    # Initialize temporal smoother
    smoother = PredictionSmoother(window_size=TEMPORAL_WINDOW_SIZE)
    
    print("\n" + "="*60)
    print("SMART ROBOT AI - REALTIME INFERENCE")
    print("="*60)
    print(f"Classes: {', '.join(CLASS_NAMES)}")
    print(f"Confidence Threshold: {CONFIDENCE_THRESHOLD * 100:.0f}%")
    print(f"Temporal Smoothing: {TEMPORAL_WINDOW_SIZE} frames")
    print("Controls: Press Q to quit")
    print("="*60 + "\n")
    
    prev_time = time.time()
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Frame capture failed.")
            break

        frame_count += 1
        
        # =====================================================
        # PREDICTION
        # =====================================================
        
        # Get raw neural network prediction
        class_index, confidence, _ = predict_with_confidence(model, frame)
        raw_prediction = get_final_prediction(class_index, confidence)
        
        # =====================================================
        # TEMPORAL SMOOTHING
        # =====================================================
        
        # Add to history and get smoothed prediction
        smoother.add_prediction(raw_prediction)
        smoothed_prediction = smoother.get_smoothed_prediction()
        
        # =====================================================
        # PERFORMANCE MONITORING
        # =====================================================
        
        current_time = time.time()
        fps = 1.0 / (current_time - prev_time) if current_time != prev_time else 0.0
        prev_time = current_time
        
        # =====================================================
        # VISUALIZATION
        # =====================================================
        
        draw_overlay(frame, raw_prediction, smoothed_prediction, confidence, fps)
        cv2.imshow("Smart Robot AI - Realtime Inference", frame)
        
        # =====================================================
        # USER INPUT
        # =====================================================
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break

    # =====================================================
    # CLEANUP
    # =====================================================
    
    cap.release()
    cv2.destroyAllWindows()
    print(f"\nRealtime inference stopped.")
    print(f"Total frames processed: {frame_count}")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
