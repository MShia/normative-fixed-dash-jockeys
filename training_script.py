"""
Complete Model Training Script for Neuropsychological Normative Data
Trains LR, LQR, and NNQR models for all test scores
"""

import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import pickle
import json
import os
from pathlib import Path
import statsmodels.formula.api as smf
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')

# Neural Network Architecture (same as dashboard)
class MultiQuantileRegressionNet(nn.Module):
    def __init__(self, input_dim, num_quantiles=99):
        super().__init__()
        self.model = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.BatchNorm1d(64),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Dropout(0.02),
            nn.Linear(64, num_quantiles)
        )

    def forward(self, x):
        return self.model(x)

def quantile_loss_soft(preds, target, quantiles, penalty_weight=2):
    """Quantile loss with monotonicity penalty"""
    pinball_losses = []
    for i, q in enumerate(quantiles):
        e = target - preds[:, i].unsqueeze(1)
        pinball_losses.append(torch.maximum(q * e, (q - 1) * e))
    
    pinball_loss = torch.mean(torch.stack(pinball_losses, dim=1))
    
    # Monotonicity penalty
    diffs = preds[:, 1:] - preds[:, :-1]
    penalty = torch.mean(torch.relu(-diffs))
    
    total_loss = pinball_loss + penalty_weight * penalty
    return total_loss

def train_neural_network(X_train, y_train, X_val, y_val, quantiles, 
                        epochs=500, lr=0.001, batch_size=32, patience=50):
    """Train neural network with early stopping"""
    
    input_dim = X_train.shape[1]
    model = MultiQuantileRegressionNet(input_dim, len(quantiles))
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=20, factor=0.8)
    
    # Convert to tensors
    X_train_tensor = torch.FloatTensor(X_train)
    y_train_tensor = torch.FloatTensor(y_train.reshape(-1, 1))
    X_val_tensor = torch.FloatTensor(X_val)
    y_val_tensor = torch.FloatTensor(y_val.reshape(-1, 1))
    quantiles_tensor = torch.FloatTensor(quantiles)
    
    # Training setup
    train_losses = []
    val_losses = []
    best_val_loss = float('inf')
    patience_counter = 0
    best_model_state = None
    
    print(f"Training Neural Network - Input dim: {input_dim}, Quantiles: {len(quantiles)}")
    
    for epoch in tqdm(range(epochs), desc="Training NN"):
        # Training
        model.train()
        
        # Mini-batch training
        train_loss_epoch = 0
        n_batches = 0
        
        for i in range(0, len(X_train), batch_size):
            batch_X = X_train_tensor[i:i+batch_size]
            batch_y = y_train_tensor[i:i+batch_size]
            
            optimizer.zero_grad()
            preds = model(batch_X)
            loss = quantile_loss_soft(preds, batch_y, quantiles_tensor)
            loss.backward()
            
            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            
            optimizer.step()
            
            train_loss_epoch += loss.item()
            n_batches += 1
        
        train_loss_epoch /= n_batches
        train_losses.append(train_loss_epoch)
        
        # Validation
        model.eval()
        with torch.no_grad():
            val_preds = model(X_val_tensor)
            val_loss = quantile_loss_soft(val_preds, y_val_tensor, quantiles_tensor).item()
            val_losses.append(val_loss)
        
        scheduler.step(val_loss)
        
        # Early stopping
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_model_state = model.state_dict().copy()
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= patience:
                print(f"Early stopping at epoch {epoch}")
                break
        
        # Print progress every 50 epochs
        if (epoch + 1) % 50 == 0:
            print(f"Epoch {epoch+1}: Train Loss = {train_loss_epoch:.4f}, Val Loss = {val_loss:.4f}")
    
    # Load best model
    model.load_state_dict(best_model_state)
    
    return model, train_losses, val_losses

def calibration_curve(preds, y_true, quantiles):
    """Calculate empirical coverage for calibration assessment"""
    if len(preds.shape) == 1:
        preds = preds.reshape(-1, 1)
    
    coverage = []
    for i in range(preds.shape[1]):
        empirical_coverage = (y_true < preds[:, i]).mean()
        coverage.append(empirical_coverage)
    
    return np.array(coverage)

def evaluate_model_coverage(model, X_test, y_test, quantiles):
    """Evaluate neural network coverage"""
    model.eval()
    with torch.no_grad():
        X_test_tensor = torch.FloatTensor(X_test)
        predictions = model(X_test_tensor).numpy()
    
    coverage = calibration_curve(predictions, y_test, quantiles)
    return coverage

def preprocess_features(df, covariates):
    """Preprocess features for neural network"""
    df_processed = df[covariates].copy()
    
    # Handle categorical variables (if any)
    df_processed = pd.get_dummies(df_processed, drop_first=True)
    
    # Convert to numeric
    df_processed = df_processed.apply(pd.to_numeric, errors='coerce')
    df_processed = df_processed.dropna()
    
    return df_processed.astype(np.float32)

def train_all_models(data_path, output_dir="models", test_size=0.2, val_size=0.1, 
                    random_state=42, nn_epochs=500):
    """
    Complete training pipeline for all models
    """
    print("=" * 60)
    print("NEUROPSYCHOLOGICAL NORMATIVE MODEL TRAINING")
    print("=" * 60)
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Load data
    print(f"\n📁 Loading data from: {data_path}")
    
    # Handle both CSV and Excel files
    if data_path.endswith('.xlsx') or data_path.endswith('.xls'):
        data = pd.read_excel(data_path)
    else:
        data = pd.read_csv(data_path)
    
    print(f"✅ Data loaded: {data.shape[0]} rows, {data.shape[1]} columns")
    print(f"📋 Columns: {list(data.columns)}")
    
    # Handle column name variations
    if 'gender' in data.columns and 'sex' not in data.columns:
        data['sex'] = data['gender']
        print("🔄 Renamed 'gender' column to 'sex'")
    
    # Define test scores and covariates
    test_scores = [col for col in data.columns if col.endswith("_raw")]
    
    # Handle different covariate names
    available_covariates = []
    covariate_mapping = {
        'age': ['age', 'Age', 'AGE'],
        'sex': ['sex', 'gender', 'Sex', 'Gender', 'GENDER'], 
        'education': ['education', 'Education', 'EDUCATION', 'educ', 'yrs_edu', 'years_education']
    }
    
    final_covariates = []
    for standard_name, possible_names in covariate_mapping.items():
        found_col = None
        for possible in possible_names:
            if possible in data.columns:
                found_col = possible
                break
        
        if found_col:
            if found_col != standard_name:
                data[standard_name] = data[found_col]
                print(f"🔄 Mapped '{found_col}' to '{standard_name}'")
            final_covariates.append(standard_name)
        else:
            print(f"⚠️  Warning: No column found for {standard_name}")
    
    covariates = final_covariates
    quantiles = np.linspace(0.01, 0.99, 99)
    
    print(f"📊 Found {len(test_scores)} test scores: {test_scores}")
    print(f"🎯 Using covariates: {covariates}")
    
    # Handle sex encoding
    if 'sex' in data.columns:
        if data['sex'].dtype == 'object':
            # Convert to numeric: Male=1, Female=0 (or reverse based on your data)
            unique_values = data['sex'].dropna().unique()
            print(f"👥 Sex values found: {unique_values}")
            
            # Create mapping - adjust this based on your data
            if any(val.lower() in ['male', 'm', 'man'] for val in unique_values):
                sex_mapping = {}
                for val in unique_values:
                    if str(val).lower() in ['male', 'm', 'man', '1']:
                        sex_mapping[val] = 1
                    elif str(val).lower() in ['female', 'f', 'woman', '0']:
                        sex_mapping[val] = 0
                    else:
                        print(f"⚠️  Unknown sex value: {val}, treating as 0")
                        sex_mapping[val] = 0
                
                data['sex'] = data['sex'].map(sex_mapping)
                print(f"🔄 Sex mapping applied: {sex_mapping}")
    
    # Initialize metadata and results tracking
    metadata = {}
    training_results = {}
    coverage_data = {}  # Store coverage information for offset calculations
    
    # Train models for each test score SEPARATELY with complete cases
    for score_idx, score in enumerate(test_scores):
        print(f"\n{'='*60}")
        print(f"🧠 TRAINING MODELS FOR {score} ({score_idx+1}/{len(test_scores)})")
        print(f"{'='*60}")
        
        # Use complete cases for THIS SPECIFIC test score only
        required_vars = covariates + [score]
        df_clean = data[required_vars].copy()
        
        # Remove rows with missing values for this specific test
        initial_size = len(df_clean)
        df_clean = df_clean.dropna()
        final_size = len(df_clean)
        
        print(f"📈 Initial samples: {initial_size}")
        print(f"📈 Complete cases for {score}: {final_size}")
        print(f"📉 Excluded due to missing data: {initial_size - final_size}")
        
        if final_size < 100:
            print(f"⚠️  Warning: Only {final_size} samples for {score}. Minimum 100 recommended. Skipping...")
            continue
        
        # Store metadata
        metadata[score] = {
            "input_dim": len(covariates),
            "feature_names": covariates,
            "score_range": [float(df_clean[score].min()), float(df_clean[score].max())],
            "sample_size": final_size,
            "training_date": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "mean_score": float(df_clean[score].mean()),
            "std_score": float(df_clean[score].std()),
            "excluded_samples": initial_size - final_size
        }
        
        # Initialize coverage data for this score
        coverage_data[score] = {}
        
        # Prepare features and target
        X = df_clean[covariates].values.astype(np.float32)
        y = df_clean[score].values.astype(np.float32)
        
        # Check for any remaining NaN values
        if np.isnan(X).any() or np.isnan(y).any():
            print(f"❌ Still have NaN values after cleaning. Skipping {score}")
            continue
        
        # Data splits
        X_temp, X_test, y_temp, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state
        )
        X_train, X_val, y_train, y_val = train_test_split(
            X_temp, y_temp, test_size=val_size/(1-test_size), random_state=random_state
        )
        
        print(f"📊 Data splits - Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")
        
        # Scale features for neural network (fit on training data only)
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_val_scaled = scaler.transform(X_val)
        X_test_scaled = scaler.transform(X_test)
        
        # Results for this score
        score_results = {
            'train_size': len(X_train),
            'val_size': len(X_val),
            'test_size': len(X_test),
            'complete_cases': final_size,
            'excluded_cases': initial_size - final_size
        }
        
        # ===============================
        # 1. TRAIN LINEAR REGRESSION
        # ===============================
        print("\n🔵 Training Linear Regression...")
        try:
            formula = f"{score} ~ {' + '.join(covariates)}"
            lr_model = smf.ols(formula, df_clean).fit()
            
            # Create model dictionary
            lr_dict = {
                "coefficients": lr_model.params.values[1:].tolist(),  # Exclude intercept
                "intercept": float(lr_model.params.values[0]),
                "feature_names": covariates,
                "mean": float(y.mean()),
                "std": float(lr_model.resid.std()),
                "r_squared": float(lr_model.rsquared),
                "aic": float(lr_model.aic),
                "bic": float(lr_model.bic)
            }
            
            # Save model
            lr_path = output_path / f"{score}_lr_model.pkl"
            with open(lr_path, 'wb') as f:
                pickle.dump(lr_dict, f)
            
            # Evaluate
            y_pred_lr = lr_model.predict(df_clean.iloc[len(X_train) + len(X_val):len(X_train) + len(X_val) + len(X_test)])
            lr_mse = mean_squared_error(y_test, y_pred_lr)
            lr_mae = mean_absolute_error(y_test, y_pred_lr)
            
            # Calculate coverage for LR using test data
            z_scores_test = (y_test - y_pred_lr) / lr_dict['std']
            percentiles_test = norm.cdf(z_scores_test)
            lr_coverage = [(percentiles_test < q).mean() for q in quantiles]
            coverage_data[score]['LR'] = lr_coverage
            
            score_results['lr'] = {
                'mse': lr_mse,
                'mae': lr_mae,
                'r_squared': lr_dict['r_squared']
            }
            
            print(f"✅ LR trained - R²: {lr_dict['r_squared']:.3f}, MSE: {lr_mse:.3f}")
            
        except Exception as e:
            print(f"❌ LR training failed: {str(e)}")
            score_results['lr'] = {'error': str(e)}
        
        # ===============================
        # 2. TRAIN LINEAR QUANTILE REGRESSION
        # ===============================
        print("\n🟡 Training Linear Quantile Regression...")
        try:
            lqr_mse_list = []
            lqr_test_preds = []
            
            for i, q in enumerate(tqdm(quantiles, desc="Training LQR")):
                qr_model = smf.quantreg(formula, df_clean).fit(q=q)
                
                lqr_dict = {
                    "coefficients": qr_model.params.values[1:].tolist(),
                    "intercept": float(qr_model.params.values[0]),
                    "quantile": float(q),
                    "feature_names": covariates
                }
                
                # Save individual quantile model
                lqr_path = output_path / f"{score}_lqr_q{i:02d}.pkl"
                with open(lqr_path, 'wb') as f:
                    pickle.dump(lqr_dict, f)
                
                # Get predictions for test set
                test_subset = df_clean.iloc[len(X_train) + len(X_val):len(X_train) + len(X_val) + len(X_test)]
                y_pred_q = qr_model.predict(test_subset)
                lqr_test_preds.append(y_pred_q.values)
                
                # Evaluate this quantile
                if i % 20 == 0:  # Evaluate every 20th quantile
                    lqr_mse_list.append(mean_squared_error(y_test, y_pred_q))
            
            # Calculate coverage for LQR
            lqr_test_preds = np.array(lqr_test_preds).T  # Shape: (n_test, n_quantiles)
            lqr_coverage = calibration_curve(lqr_test_preds, y_test, quantiles)
            coverage_data[score]['LQR'] = lqr_coverage.tolist()
            
            score_results['lqr'] = {
                'mean_mse': np.mean(lqr_mse_list),
                'quantiles_trained': len(quantiles)
            }
            
            print(f"✅ LQR trained - {len(quantiles)} quantiles, Mean MSE: {np.mean(lqr_mse_list):.3f}")
            
        except Exception as e:
            print(f"❌ LQR training failed: {str(e)}")
            score_results['lqr'] = {'error': str(e)}
        
        # ===============================
        # 3. TRAIN NEURAL NETWORK
        # ===============================
        print("\n🔴 Training Neural Network Quantile Regression...")
        try:
            # Train neural network
            nn_model, train_losses, val_losses = train_neural_network(
                X_train_scaled, y_train, X_val_scaled, y_val, 
                quantiles, epochs=nn_epochs
            )
            
            # Save model
            nn_path = output_path / f"{score}_nnqr_model.pth"
            torch.save(nn_model.state_dict(), nn_path)
            
            # Save scaler
            scaler_path = output_path / f"{score}_scaler.pkl"
            with open(scaler_path, 'wb') as f:
                pickle.dump(scaler, f)
            
            # Evaluate neural network
            nn_model.eval()
            with torch.no_grad():
                X_test_tensor = torch.FloatTensor(X_test_scaled)
                nn_predictions = nn_model(X_test_tensor).numpy()
            
            # Calculate coverage
            coverage = evaluate_model_coverage(nn_model, X_test_scaled, y_test, quantiles)
            coverage_error = np.mean(np.abs(coverage - quantiles))
            coverage_data[score]['NNQR'] = coverage.tolist()
            
            # MSE for median prediction (50th percentile)
            median_idx = len(quantiles) // 2
            nn_mse = mean_squared_error(y_test, nn_predictions[:, median_idx])
            nn_mae = mean_absolute_error(y_test, nn_predictions[:, median_idx])
            
            score_results['nnqr'] = {
                'mse': nn_mse,
                'mae': nn_mae,
                'coverage_error': coverage_error,
                'final_train_loss': train_losses[-1],
                'final_val_loss': val_losses[-1],
                'epochs_trained': len(train_losses)
            }
            
            print(f"✅ NNQR trained - MSE: {nn_mse:.3f}, Coverage Error: {coverage_error:.4f}")
            
            # Plot training curves
            if len(train_losses) > 10:
                plt.figure(figsize=(12, 4))
                
                plt.subplot(1, 3, 1)
                plt.plot(train_losses, label='Train Loss')
                plt.plot(val_losses, label='Validation Loss')
                plt.xlabel('Epoch')
                plt.ylabel('Loss')
                plt.title(f'NN Training Curves - {score}')
                plt.legend()
                plt.grid(True, alpha=0.3)
                
                plt.subplot(1, 3, 2)
                plt.plot(quantiles * 100, coverage * 100, label='Empirical Coverage', alpha=0.7)
                plt.plot(quantiles * 100, quantiles * 100, 'r--', label='Perfect Coverage')
                plt.xlabel('Theoretical Percentile')
                plt.ylabel('Empirical Percentile')
                plt.title(f'Coverage Plot - {score}')
                plt.legend()
                plt.grid(True, alpha=0.3)
                
                plt.subplot(1, 3, 3)
                # Coverage offset plot
                offset_nn = np.abs(coverage - quantiles)
                plt.plot(quantiles * 100, offset_nn, label='NNQR Coverage Offset', color='blue')
                if score in coverage_data and 'LQR' in coverage_data[score]:
                    offset_lqr = np.abs(np.array(coverage_data[score]['LQR']) - quantiles)
                    plt.plot(quantiles * 100, offset_lqr, label='LQR Coverage Offset', color='orange')
                if score in coverage_data and 'LR' in coverage_data[score]:
                    offset_lr = np.abs(np.array(coverage_data[score]['LR']) - quantiles)
                    plt.plot(quantiles * 100, offset_lr, label='LR Coverage Offset', color='green')
                plt.xlabel('Percentile')
                plt.ylabel('Coverage Offset')
                plt.title(f'Coverage Offset Comparison - {score}')
                plt.legend()
                plt.grid(True, alpha=0.3)
                
                plt.tight_layout()
                plot_path = output_path / f"{score}_diagnostics.png"
                plt.savefig(plot_path, dpi=150, bbox_inches='tight')
                plt.close()
            
        except Exception as e:
            print(f"❌ NNQR training failed: {str(e)}")
            score_results['nnqr'] = {'error': str(e)}
        
        # Store results for this score
        training_results[score] = score_results
        
        print(f"✅ Completed training for {score}")
    
    # ===============================
    # SAVE METADATA AND RESULTS
    # ===============================
    print(f"\n{'='*60}")
    print("💾 SAVING METADATA AND RESULTS")
    print(f"{'='*60}")
    
    # Save model metadata
    metadata_path = output_path / "model_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"✅ Metadata saved to: {metadata_path}")
    
    # Save training results
    results_path = output_path / "training_results.json"
    with open(results_path, 'w') as f:
        json.dump(training_results, f, indent=2)
    print(f"✅ Training results saved to: {results_path}")
    
    # Save coverage data for dashboard use
    coverage_path = output_path / "coverage_data.json"
    with open(coverage_path, 'w') as f:
        json.dump(coverage_data, f, indent=2)
    print(f"✅ Coverage data saved to: {coverage_path}")
    
    # Generate summary report
    summary_path = output_path / "training_summary.txt"
    with open(summary_path, 'w') as f:
        f.write("NEUROPSYCHOLOGICAL NORMATIVE MODELS - TRAINING SUMMARY\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Training Date: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total Test Scores: {len(test_scores)}\n")
        f.write(f"Covariates: {', '.join(covariates)}\n")
        f.write(f"Quantiles: {len(quantiles)}\n\n")
        
        f.write("MODEL PERFORMANCE SUMMARY:\n")
        f.write("-" * 30 + "\n")
        
        for score in training_results:
            f.write(f"\n{score}:\n")
            if 'lr' in training_results[score] and 'mse' in training_results[score]['lr']:
                f.write(f"  LR  - MSE: {training_results[score]['lr']['mse']:.3f}\n")
            if 'lqr' in training_results[score] and 'mean_mse' in training_results[score]['lqr']:
                f.write(f"  LQR - MSE: {training_results[score]['lqr']['mean_mse']:.3f}\n")
            if 'nnqr' in training_results[score] and 'mse' in training_results[score]['nnqr']:
                f.write(f"  NNQR- MSE: {training_results[score]['nnqr']['mse']:.3f}\n")
        
        f.write(f"\nCOVERAGE DATA:\n")
        f.write("-" * 15 + "\n")
        f.write(f"Coverage data computed for {len(coverage_data)} test scores\n")
        f.write("This data enables optimal method selection in the dashboard\n")
    
  
    # List all generated files
    print(f"\n📁 GENERATED FILES:")
    print(f"📂 Output directory: {output_path.absolute()}")
    
    all_files = list(output_path.glob("*"))
    for file_path in sorted(all_files):
        size_mb = file_path.stat().st_size / (1024 * 1024)
        print(f"  📄 {file_path.name} ({size_mb:.2f} MB)")
    
    print(f"\n🎉 TRAINING COMPLETED SUCCESSFULLY!")
    print(f"✅ Trained models for {len([s for s in training_results if 'error' not in str(training_results[s])])} test scores")
    print(f"📊 Models ready for deployment in dashboard")
    
    return metadata, training_results

def validate_generated_models(models_dir="models"):
    """
    Validate that all models were generated correctly
    """
    print(f"\n{'='*60}")
    print("🔍 VALIDATING GENERATED MODELS")
    print(f"{'='*60}")
    
    models_path = Path(models_dir)
    
    # Load metadata
    metadata_path = models_path / "model_metadata.json"
    if not metadata_path.exists():
        print("❌ No metadata file found!")
        return False
    
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    
    print(f"📊 Found metadata for {len(metadata)} test scores")
    
    validation_results = {}
    
    for score in metadata:
        print(f"\n🧠 Validating {score}...")
        score_validation = {}
        
        # Check LR model
        lr_path = models_path / f"{score}_lr_model.pkl"
        if lr_path.exists():
            try:
                with open(lr_path, 'rb') as f:
                    lr_model = pickle.load(f)
                print(f"  ✅ LR model loaded successfully")
                score_validation['lr'] = True
            except Exception as e:
                print(f"  ❌ LR model error: {str(e)}")
                score_validation['lr'] = False
        else:
            print(f"  ❌ LR model file not found")
            score_validation['lr'] = False
        
        # Check LQR models
        lqr_count = 0
        for i in range(99):
            lqr_path = models_path / f"{score}_lqr_q{i:02d}.pkl"
            if lqr_path.exists():
                lqr_count += 1
        
        if lqr_count == 99:
            print(f"  ✅ All 99 LQR models found")
            score_validation['lqr'] = True
        else:
            print(f"  ❌ Only {lqr_count}/99 LQR models found")
            score_validation['lqr'] = False
        
        # Check NNQR model
        nnqr_path = models_path / f"{score}_nnqr_model.pth"
        scaler_path = models_path / f"{score}_scaler.pkl"
        
        if nnqr_path.exists() and scaler_path.exists():
            try:
                # Load scaler
                with open(scaler_path, 'rb') as f:
                    scaler = pickle.load(f)
                
                # Load NN model
                input_dim = metadata[score]['input_dim']
                model = MultiQuantileRegressionNet(input_dim)
                model.load_state_dict(torch.load(nnqr_path, map_location='cpu'))
                model.eval()
                
                # Test prediction
                dummy_input = torch.randn(1, input_dim)
                with torch.no_grad():
                    output = model(dummy_input)
                
                if output.shape[1] == 99:
                    print(f"  ✅ NNQR model loaded and tested successfully")
                    score_validation['nnqr'] = True
                else:
                    print(f"  ❌ NNQR model output shape incorrect: {output.shape}")
                    score_validation['nnqr'] = False
                    
            except Exception as e:
                print(f"  ❌ NNQR model error: {str(e)}")
                score_validation['nnqr'] = False
        else:
            print(f"  ❌ NNQR model or scaler not found")
            score_validation['nnqr'] = False
        
        validation_results[score] = score_validation
    
    # Summary
    total_scores = len(validation_results)
    successful_lr = sum(1 for v in validation_results.values() if v.get('lr', False))
    successful_lqr = sum(1 for v in validation_results.values() if v.get('lqr', False))
    successful_nnqr = sum(1 for v in validation_results.values() if v.get('nnqr', False))
    
    print(f"\n📊 VALIDATION SUMMARY:")
    print(f"  LR models:   {successful_lr}/{total_scores} successful")
    print(f"  LQR models:  {successful_lqr}/{total_scores} successful")
    print(f"  NNQR models: {successful_nnqr}/{total_scores} successful")
    
    all_successful = (successful_lr == total_scores and 
                     successful_lqr == total_scores and 
                     successful_nnqr == total_scores)
    
    if all_successful:
        print(f"\n🎉 ALL MODELS VALIDATED SUCCESSFULLY!")
        print(f"✅ Ready for dashboard deployment")
    else:
        print(f"\n⚠️  Some models failed validation")
        print(f"❌ Check training logs for errors")
    
    return all_successful

if __name__ == "__main__":
    # Configuration for your specific data
    DATA_PATH = "normative_test_file_dashboard.xlsx"  # Update this to your Excel file path
    OUTPUT_DIR = "models"
    
    # Training parameters
    TEST_SIZE = 0.2      # 20% for testing
    VAL_SIZE = 0.1       # 10% for validation
    RANDOM_STATE = 42    # For reproducibility
    NN_EPOCHS = 300      # Reduced epochs for smaller dataset
    
    print("🚀 Starting model training for neuropsychological data...")
    print(f"📊 Expected test scores: DSF_raw, DSB_raw, SOC_raw, SDMT_raw")
    print(f"📊 Expected demographics: age, education, gender")
    
    # Check if data file exists
    if not os.path.exists(DATA_PATH):
        print(f"❌ Data file not found: {DATA_PATH}")
        print("Please update DATA_PATH with the correct path to your Excel file")
        print("Example: DATA_PATH = 'path/to/your/neuropsych_data.xlsx'")
        exit(1)
    
    try:
        # Train all models
        metadata, results = train_all_models(
            data_path=DATA_PATH,
            output_dir=OUTPUT_DIR,
            test_size=TEST_SIZE,
            val_size=VAL_SIZE,
            random_state=RANDOM_STATE,
            nn_epochs=NN_EPOCHS
        )
        
        # Validate generated models
        validation_success = validate_generated_models(OUTPUT_DIR)
        
        if validation_success:
            print(f"\n🎯 NEXT STEPS:")
            print(f"1. Copy the '{OUTPUT_DIR}' directory to your dashboard project")
            print(f"2. Update dashboard configuration if needed")
            print(f"3. Run the dashboard: streamlit run app.py")
            print(f"4. Test with your specific test scores:")
            print(f"   - DSF_raw (Digit Span Forward)")
            print(f"   - DSB_raw (Digit Span Backward)")  
            print(f"   - SOC_raw (Stockings of Cambridge)")
            print(f"   - SDMT_raw (Symbol Digit Modalities Test)")
            
        else:
            print(f"\n⚠️  VALIDATION FAILED:")
            print(f"Some models may need to be retrained")
            print(f"Check the error messages above for details")
    
    except Exception as e:
        print(f"\n❌ TRAINING FAILED:")
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Provide specific troubleshooting for common issues
        print(f"\n🔧 TROUBLESHOOTING:")
        print(f"1. Check your Excel file path: {DATA_PATH}")
        print(f"2. Verify column names: ['age', 'education', 'gender', 'DSF_raw', 'DSB_raw', 'SOC_raw', 'SDMT_raw']")
        print(f"3. Ensure data types are numeric for scores and demographics")
        print(f"4. Check for sufficient sample sizes (>100 complete cases per test)")
        
def check_data_compatibility(data_path):
    """
    Check if your data is compatible with the training script
    """
    print("🔍 CHECKING DATA COMPATIBILITY...")
    
    try:
        # Load data
        if data_path.endswith('.xlsx') or data_path.endswith('.xls'):
            df = pd.read_excel(data_path)
        else:
            df = pd.read_csv(data_path)
        
        print(f"✅ Data loaded successfully: {df.shape}")
        print(f"📋 Columns found: {list(df.columns)}")
        
        # Check required columns
        expected_scores = ['DSF_raw', 'DSB_raw', 'SOC_raw', 'SDMT_raw']
        expected_demos = ['age', 'education']
        expected_gender = ['gender', 'sex']
        
        found_scores = [col for col in expected_scores if col in df.columns]
        found_demos = [col for col in expected_demos if col in df.columns]
        found_gender = [col for col in expected_gender if col in df.columns]
        
        print(f"\n📊 TEST SCORES:")
        for score in expected_scores:
            if score in df.columns:
                complete_cases = df[score].notna().sum()
                print(f"  ✅ {score}: {complete_cases} complete cases")
            else:
                print(f"  ❌ {score}: NOT FOUND")
        
        print(f"\n👤 DEMOGRAPHICS:")
        for demo in expected_demos:
            if demo in df.columns:
                complete_cases = df[demo].notna().sum()
                print(f"  ✅ {demo}: {complete_cases} complete cases")
            else:
                print(f"  ❌ {demo}: NOT FOUND")
        
        if found_gender:
            gender_col = found_gender[0]
            unique_vals = df[gender_col].dropna().unique()
            print(f"  ✅ {gender_col}: {len(df[gender_col].dropna())} complete cases")
            print(f"    Values: {list(unique_vals)}")
        else:
            print(f"  ❌ gender/sex: NOT FOUND")
        
        # Check complete cases for each test
        print(f"\n📈 COMPLETE CASES PER TEST:")
        for score in found_scores:
            required_cols = found_demos + found_gender + [score]
            available_cols = [col for col in required_cols if col in df.columns]
            complete_cases = df[available_cols].dropna()
            
            print(f"  {score}: {len(complete_cases)} complete cases")
            if len(complete_cases) < 100:
                print(f"    ⚠️  WARNING: Less than 100 cases (minimum recommended)")
            else:
                print(f"    ✅ Sufficient for training")
        
        # Overall compatibility
        min_requirements = (
            len(found_scores) >= 1 and
            len(found_demos) >= 2 and
            len(found_gender) >= 1
        )
        
        if min_requirements:
            print(f"\n🎉 DATA IS COMPATIBLE!")
            print(f"✅ Ready for model training")
            return True
        else:
            print(f"\n❌ DATA COMPATIBILITY ISSUES FOUND")
            print(f"Please check the missing columns above")
            return False
            
    except Exception as e:
        print(f"❌ Error checking data: {e}")
        return False

# Add this function call before training if you want to check compatibility first
# check_data_compatibility("your_data.xlsx")