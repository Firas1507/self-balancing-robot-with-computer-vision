import os
import tensorflow as tf

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")
H5_PATH = os.path.join(MODEL_DIR, "smart_robot_model.h5")
TFLITE_PATH = os.path.join(MODEL_DIR, "smart_robot_model.tflite")


def convert_to_tflite():
    if not os.path.exists(H5_PATH):
        raise FileNotFoundError(f"Trained model not found at {H5_PATH}. Run train_model.py first.")

    model = tf.keras.models.load_model(H5_PATH)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]

    try:
        tflite_model = converter.convert()
    except Exception as error:
        raise RuntimeError("TensorFlow Lite conversion failed") from error

    with open(TFLITE_PATH, "wb") as f:
        f.write(tflite_model)

    print(f"Converted model saved to: {TFLITE_PATH}")


def main():
    try:
        convert_to_tflite()
    except (FileNotFoundError, RuntimeError) as error:
        print(error)


if __name__ == "__main__":
    main()
