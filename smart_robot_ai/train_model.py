import os
import cv2
import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt
import seaborn as sns

from tensorflow.keras import layers, models
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.callbacks import (
    EarlyStopping,
    ModelCheckpoint,
    ReduceLROnPlateau
)

from sklearn.metrics import (
    confusion_matrix,
    classification_report
)

# =========================================================
# GPU MEMORY GROWTH (OPTIONAL)
# =========================================================

gpus = tf.config.experimental.list_physical_devices('GPU')

if gpus:
    try:
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)

        print("[INFO] GPU memory growth enabled.")

    except RuntimeError as e:
        print(e)

# =========================================================
# PATHS
# =========================================================

BASE_DIR = os.path.dirname(__file__)

DATASET_DIR = os.path.join(BASE_DIR, "dataset")

MODEL_DIR = os.path.join(BASE_DIR, "model")

os.makedirs(MODEL_DIR, exist_ok=True)

# =========================================================
# CONFIG
# =========================================================

CLASS_NAMES = ["go", "stop", "left", "right", "none"]

IMAGE_SIZE = (96, 96)

BATCH_SIZE = 32

EPOCHS_PHASE1 = 15

EPOCHS_PHASE2 = 15

TEST_SPLIT = 0.2

LEARNING_RATE_PHASE1 = 0.001

LEARNING_RATE_PHASE2 = 0.00001

MODEL_PATH = os.path.join(
    MODEL_DIR,
    "smart_robot_mobilenetv2.keras"
)

# =========================================================
# DATA AUGMENTATION
# =========================================================

# IMPORTANT:
# No horizontal flip because:
# LEFT <-> RIGHT corruption

data_augmentation = tf.keras.Sequential([

    layers.RandomRotation(0.15),

    layers.RandomZoom(0.20),

    layers.RandomContrast(0.20),

    layers.RandomTranslation(
        height_factor=0.10,
        width_factor=0.10
    ),

])

# =========================================================
# LOAD IMAGES
# =========================================================

def load_images_from_folder(folder, label):

    images = []

    labels = []

    if not os.path.exists(folder):

        print(f"[WARNING] Missing folder: {folder}")

        return images, labels

    for filename in os.listdir(folder):

        if filename.lower().endswith((".jpg", ".jpeg", ".png")):

            filepath = os.path.join(folder, filename)

            image = cv2.imread(filepath)

            if image is None:
                continue

            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            image = cv2.resize(image, IMAGE_SIZE)

            images.append(image)

            labels.append(label)

    return images, labels

# =========================================================
# BUILD DATASET
# =========================================================

def build_dataset():

    all_images = []

    all_labels = []

    print("\n==============================")
    print("LOADING DATASET")
    print("==============================\n")

    for index, class_name in enumerate(CLASS_NAMES):

        folder = os.path.join(DATASET_DIR, class_name)

        images, labels = load_images_from_folder(
            folder,
            index
        )

        print(
            f"[INFO] {class_name:<10} : {len(images)} images"
        )

        all_images.extend(images)

        all_labels.extend(labels)

    if len(all_images) == 0:
        raise ValueError("Dataset is empty.")

    x = np.array(all_images, dtype=np.float32)

    y = np.array(all_labels, dtype=np.int32)

    # Normalize
    x = x / 255.0

    return x, y

# =========================================================
# SPLIT DATASET
# =========================================================

def split_dataset(x, y):

    indices = np.arange(len(x))

    np.random.seed(42)

    np.random.shuffle(indices)

    x = x[indices]

    y = y[indices]

    split_index = int(len(x) * (1 - TEST_SPLIT))

    x_train = x[:split_index]

    y_train = y[:split_index]

    x_test = x[split_index:]

    y_test = y[split_index:]

    return x_train, x_test, y_train, y_test

# =========================================================
# BUILD MODEL
# =========================================================

def build_model():

    # =====================================================
    # PRETRAINED BACKBONE
    # =====================================================

    base_model = MobileNetV2(

        input_shape=(IMAGE_SIZE[0], IMAGE_SIZE[1], 3),

        include_top=False,

        weights="imagenet"

    )

    # Freeze backbone initially
    base_model.trainable = False

    # =====================================================
    # INPUT
    # =====================================================

    inputs = layers.Input(
        shape=(IMAGE_SIZE[0], IMAGE_SIZE[1], 3)
    )

    # =====================================================
    # AUGMENTATION
    # =====================================================

    x = data_augmentation(inputs)

    # =====================================================
    # FEATURE EXTRACTION
    # =====================================================

    x = base_model(x, training=False)

    # =====================================================
    # CLASSIFIER
    # =====================================================

    x = layers.GlobalAveragePooling2D()(x)

    x = layers.BatchNormalization()(x)

    x = layers.Dropout(0.4)(x)

    x = layers.Dense(
        128,
        activation="relu"
    )(x)

    x = layers.Dropout(0.3)(x)

    outputs = layers.Dense(
        len(CLASS_NAMES),
        activation="softmax"
    )(x)

    model = models.Model(inputs, outputs)

    # =====================================================
    # COMPILE
    # =====================================================

    model.compile(

        optimizer=tf.keras.optimizers.Adam(
            learning_rate=LEARNING_RATE_PHASE1
        ),

        loss=tf.keras.losses.SparseCategoricalCrossentropy(),

        metrics=["accuracy"]

    )

    return model, base_model

# =========================================================
# PLOT HISTORY
# =========================================================

def plot_history(history1, history2):

    acc = (
        history1.history["accuracy"] +
        history2.history["accuracy"]
    )

    val_acc = (
        history1.history["val_accuracy"] +
        history2.history["val_accuracy"]
    )

    loss = (
        history1.history["loss"] +
        history2.history["loss"]
    )

    val_loss = (
        history1.history["val_loss"] +
        history2.history["val_loss"]
    )

    epochs_range = range(len(acc))

    plt.figure(figsize=(12, 5))

    # Accuracy
    plt.subplot(1, 2, 1)

    plt.plot(epochs_range, acc, label="Train Accuracy")

    plt.plot(epochs_range, val_acc,
             label="Validation Accuracy")

    plt.legend(loc="lower right")

    plt.title("Training Accuracy")

    # Loss
    plt.subplot(1, 2, 2)

    plt.plot(epochs_range, loss, label="Train Loss")

    plt.plot(epochs_range, val_loss,
             label="Validation Loss")

    plt.legend(loc="upper right")

    plt.title("Training Loss")

    plt.show()

# =========================================================
# CONFUSION MATRIX
# =========================================================

def show_confusion_matrix(model, x_test, y_test):

    predictions = model.predict(x_test)

    predicted_classes = np.argmax(
        predictions,
        axis=1
    )

    cm = confusion_matrix(
        y_test,
        predicted_classes
    )

    plt.figure(figsize=(8, 6))

    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        xticklabels=CLASS_NAMES,
        yticklabels=CLASS_NAMES
    )

    plt.xlabel("Predicted")

    plt.ylabel("Actual")

    plt.title("Confusion Matrix")

    plt.show()

    print("\n==============================")
    print("CLASSIFICATION REPORT")
    print("==============================\n")

    print(classification_report(
        y_test,
        predicted_classes,
        target_names=CLASS_NAMES
    ))

# =========================================================
# EXPORT TFLITE
# =========================================================

def export_tflite(model):

    print("\n[INFO] Exporting TFLite model...")

    converter = tf.lite.TFLiteConverter.from_keras_model(
        model
    )

    # Dynamic range quantization
    converter.optimizations = [
        tf.lite.Optimize.DEFAULT
    ]

    tflite_model = converter.convert()

    tflite_path = os.path.join(
        MODEL_DIR,
        "smart_robot_model.tflite"
    )

    with open(tflite_path, "wb") as f:
        f.write(tflite_model)

    print(f"[INFO] TFLite saved to:\n{tflite_path}")

# =========================================================
# MAIN
# =========================================================

def main():

    print("\n==============================")
    print("SMART ROBOT ADVANCED TRAINING")
    print("==============================\n")

    # =====================================================
    # LOAD DATA
    # =====================================================

    x, y = build_dataset()

    # =====================================================
    # SPLIT
    # =====================================================

    x_train, x_test, y_train, y_test = split_dataset(
        x,
        y
    )

    print(f"\nTraining samples  : {len(x_train)}")

    print(f"Validation samples: {len(x_test)}")

    # =====================================================
    # BUILD MODEL
    # =====================================================

    model, base_model = build_model()

    model.summary()

    # =====================================================
    # CALLBACKS
    # =====================================================

    early_stopping = EarlyStopping(

        monitor="val_loss",

        patience=5,

        restore_best_weights=True

    )

    checkpoint = ModelCheckpoint(

        MODEL_PATH,

        monitor="val_accuracy",

        save_best_only=True,

        verbose=1

    )

    reduce_lr = ReduceLROnPlateau(

        monitor="val_loss",

        factor=0.5,

        patience=2,

        verbose=1

    )

    # =====================================================
    # PHASE 1
    # FEATURE EXTRACTION
    # =====================================================

    print("\n==============================")
    print("PHASE 1 - FEATURE EXTRACTION")
    print("==============================\n")

    history1 = model.fit(

        x_train,

        y_train,

        validation_data=(x_test, y_test),

        epochs=EPOCHS_PHASE1,

        batch_size=BATCH_SIZE,

        callbacks=[
            early_stopping,
            checkpoint,
            reduce_lr
        ],

        verbose=2

    )

    # =====================================================
    # PHASE 2
    # FINE TUNING
    # =====================================================

    print("\n==============================")
    print("PHASE 2 - FINE TUNING")
    print("==============================\n")

    # Unfreeze top layers
    base_model.trainable = True

    # Freeze lower layers
    for layer in base_model.layers[:-30]:
        layer.trainable = False

    model.compile(

        optimizer=tf.keras.optimizers.Adam(
            learning_rate=LEARNING_RATE_PHASE2
        ),

        loss=tf.keras.losses.SparseCategoricalCrossentropy(),

        metrics=["accuracy"]

    )

    history2 = model.fit(

        x_train,

        y_train,

        validation_data=(x_test, y_test),

        epochs=EPOCHS_PHASE2,

        batch_size=BATCH_SIZE,

        callbacks=[
            early_stopping,
            checkpoint,
            reduce_lr
        ],

        verbose=2

    )

    # =====================================================
    # FINAL EVALUATION
    # =====================================================

    print("\n==============================")
    print("FINAL EVALUATION")
    print("==============================\n")

    loss, accuracy = model.evaluate(
        x_test,
        y_test,
        verbose=0
    )

    print(f"Test Accuracy : {accuracy * 100:.2f}%")

    print(f"Test Loss     : {loss:.4f}")

    # =====================================================
    # SAVE MODEL
    # =====================================================

    model.save(MODEL_PATH)

    print(f"\n[INFO] Model saved to:\n{MODEL_PATH}")

    # =====================================================
    # EXPORT TFLITE
    # =====================================================

    export_tflite(model)

    # =====================================================
    # VISUALIZATION
    # =====================================================

    plot_history(history1, history2)

    show_confusion_matrix(
        model,
        x_test,
        y_test
    )

    print("\n==============================")
    print("TRAINING FINISHED")
    print("==============================\n")

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()