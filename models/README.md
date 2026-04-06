# Models Directory

Place your trained machine learning models here.

## File Placement Instructions

### Anomaly Detection Models
- **anomaly_detector.h5**: Primary anomaly detection model (Keras .h5 format)
- **deep_learning_detector.h5**: LSTM/RNN-based deep learning detector (Keras .h5 format)

## Model Format

All models should be in Keras/TensorFlow HDF5 format (.h5).

### Example: Saving a Model
```python
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, LSTM

model = Sequential([
    LSTM(64, input_shape=(50, 10)),
    Dense(32, activation='relu'),
    Dense(1, activation='sigmoid')
])

model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
model.fit(X_train, y_train, epochs=10)

# Save the model
model.save('anomaly_detector.h5')
```

## Usage in Code

Models are loaded in `src/anomaly_detection/ml_detector.py` and `src/anomaly_detection/deep_learning_detector.py`:

```python
from tensorflow.keras.models import load_model
model = load_model('models/anomaly_detector.h5')
predictions = model.predict(data)
```

## Notes

- Models are referenced in `config/constants.py`
- The `.gitkeep` file allows the empty directory to be tracked in Git
- Never commit large model files to Git - use Git LFS or store them separately
