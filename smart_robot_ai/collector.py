import os
import cv2
import time

# Directory names for each command class
# IMPORTANT: "none" class is for non-sign images (random objects, backgrounds)
# This is CRITICAL for training robust models that don't produce false positives
CLASS_NAMES = ["go", "stop", "left", "right", "none"]
DATASET_DIR = os.path.join(os.path.dirname(__file__), "dataset")
IMAGE_SIZE = (64, 64)


def ensure_dataset_folders():
    """Create dataset folders if they do not exist."""
    for class_name in CLASS_NAMES:
        folder = os.path.join(DATASET_DIR, class_name)
        os.makedirs(folder, exist_ok=True)


def count_images():
    """Count saved images in each class folder."""
    counters = {}
    for class_name in CLASS_NAMES:
        folder = os.path.join(DATASET_DIR, class_name)
        files = [f for f in os.listdir(folder) if f.lower().endswith(".png") or f.lower().endswith(".jpg")]
        counters[class_name] = len(files)
    return counters


def get_unique_filename(folder, prefix):
    """Generate a unique filename based on timestamp."""
    timestamp = int(time.time() * 1000)
    return os.path.join(folder, f"{prefix}_{timestamp}.png")


def save_frame(frame, class_name):
    """Resize and save the camera frame to the dataset folder."""
    folder = os.path.join(DATASET_DIR, class_name)
    filename = get_unique_filename(folder, class_name)
    resized = cv2.resize(frame, IMAGE_SIZE)
    cv2.imwrite(filename, resized)


def draw_status(frame, current_class, counters):
    """Draw status text on the video frame."""
    height = frame.shape[0]
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 70), (0, 0, 0), -1)
    cv2.putText(frame, "Smart Robot Command Collector", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, "Press G=GO S=STOP L=LEFT R=RIGHT N=NONE | Q=QUIT", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    cv2.putText(frame, f"Current: {current_class}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    y = 110
    for class_name in CLASS_NAMES:
        cv2.putText(frame, f"{class_name}: {counters[class_name]}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1)
        y += 25


def main():
    ensure_dataset_folders()
    counters = count_images()
    current_class = "none"

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Cannot open webcam. Make sure a camera is connected.")
        return

    print("Collector started. Press G, S, L, or R to save images.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Warning: Failed to read frame from webcam.")
            break

        display_frame = frame.copy()
        draw_status(display_frame, current_class, counters)

        cv2.imshow("Collector - Smart Robot AI", display_frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        elif key == ord("g"):
            current_class = "go"
            save_frame(frame, current_class)
            counters[current_class] += 1
        elif key == ord("s"):
            current_class = "stop"
            save_frame(frame, current_class)
            counters[current_class] += 1
        elif key == ord("l"):
            current_class = "left"
            save_frame(frame, current_class)
            counters[current_class] += 1
        elif key == ord("r"):
            current_class = "right"
            save_frame(frame, current_class)
            counters[current_class] += 1
        elif key == ord("n"):
            current_class = "none"
            save_frame(frame, current_class)
            counters[current_class] += 1

    cap.release()
    cv2.destroyAllWindows()
    print("Collector stopped.")
    print("Final counts:")
    for class_name, count in counters.items():
        print(f"  {class_name}: {count}")


if __name__ == "__main__":
    main()
