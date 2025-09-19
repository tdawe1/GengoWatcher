# Local CAPTCHA Solver

## Overview

The local CAPTCHA solver provides a machine learning-based approach to solve CAPTCHAs without relying on external services. This document explains how to configure and use the local solver.

## Features

### Supported Approaches
1. **Simple Demo Solver**: Placeholder implementation for testing
2. **TensorFlow-based Solver**: CNN-based image CAPTCHA solver (if TensorFlow is available)
3. **Extensible Architecture**: Framework for adding new ML approaches

### Current Limitations
- Only supports image-based CAPTCHAs
- Does not support reCAPTCHA v2/v3 or hCaptcha
- Requires training data and models for real-world usage

## Installation

### Basic Usage
The simple solver works out of the box with no additional dependencies.

### TensorFlow Solver
To use the TensorFlow-based solver, install TensorFlow:

```bash
pip install tensorflow
```

Note: TensorFlow requires significant system resources and may not be suitable for all systems.

## Configuration

Add the following to your `config.ini`:

```ini
[LocalCaptcha]
# Preferred solver: simple, tensorflow
preferred_solver = simple

# Path to TensorFlow model (if using TensorFlow solver)
tensorflow_model_path = models/captcha_model.h5
```

## Usage

### Programmatic Usage

```python
from gengowatcher.local_captcha_solver import LocalCaptchaSolverManager

# Initialize the solver manager
local_solver = LocalCaptchaSolverManager(config, logger)

# Check if solver is supported
if local_solver.is_supported():
    # Initialize the solver
    if local_solver.initialize():
        # Solve a CAPTCHA image
        solution = local_solver.solve_image_captcha("path/to/captcha.png")
        if solution:
            print(f"CAPTCHA solved: {solution.solution}")
        else:
            print("Failed to solve CAPTCHA")
else:
    print("Local CAPTCHA solver not supported on this system")
```

### CLI Commands

The local solver can be integrated into the CLI, but no specific commands are implemented yet.

## Implementation Details

### Simple Solver
A placeholder implementation for testing the framework. Does not actually solve CAPTCHAs.

### TensorFlow Solver
Uses convolutional neural networks to analyze CAPTCHA images:

1. **Image Preprocessing**: Resize, normalize, and prepare images for the model
2. **Model Inference**: Run the trained model on the preprocessed image
3. **Text Extraction**: Convert model output to readable text

### Extending with New Solvers
To add a new solver:

1. Create a new class that inherits from `BaseLocalCaptchaSolver`
2. Implement the required abstract methods
3. Add the solver to `LocalCaptchaSolverManager._load_solvers()`

## Training Your Own Models

To create effective local CAPTCHA solvers, you'll need to train models on CAPTCHA datasets:

1. **Data Collection**: Gather thousands of CAPTCHA images with known solutions
2. **Data Preprocessing**: Clean and standardize the images
3. **Model Training**: Train CNN or other ML models on the dataset
4. **Model Evaluation**: Test accuracy on held-out data
5. **Model Deployment**: Save and integrate trained models

## Legal and Ethical Considerations

Before implementing or using CAPTCHA-solving technology:

1. **Check Terms of Service**: Many services explicitly prohibit automated CAPTCHA solving
2. **Respect Rate Limits**: Avoid overloading services with requests
3. **Consider Alternatives**: Use official APIs when available
4. **Comply with Laws**: Follow applicable laws and regulations

## Performance Considerations

Local CAPTCHA solving can be resource-intensive:

1. **Memory Usage**: ML models can require significant RAM
2. **CPU/GPU Usage**: Model inference may be computationally expensive
3. **Accuracy**: Local solvers may have lower accuracy than specialized services
4. **Maintenance**: Models may need retraining as CAPTCHAs evolve

## Future Improvements

1. **PyTorch Support**: Add support for PyTorch-based models
2. **Model Zoo**: Pre-trained models for common CAPTCHA types
3. **Performance Optimization**: GPU acceleration and model quantization
4. **Advanced Techniques**: GANs, attention mechanisms, and ensemble methods