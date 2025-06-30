# 🧠 Neuropsychological Normative Calculator

A professional web application for calculating demographic-adjusted normative percentiles in neuropsychological assessments. Built with Streamlit for clinicians and researchers to complement the exisiting concussion protocols. The trained models are fixed and based on the Retrospective Data of Irish Horse Jockeys from 2010 - 2024. For using own data the training script can be used to train and save the models. 

## 🎯 What It Does

Transform raw cognitive test scores into meaningful percentiles by accounting for age, sex, and education. The calculator uses three advanced statistical methods and intelligently selects the most accurate result based on coverage analysis.

### Key Features
- **Multi-Method Analysis**: Compares Linear Regression (LR), Linear Quantile Regression (LQR), and Neural Network Quantile Regression (NNQR)
- **Smart Selection**: Automatically chooses the best method based on statistical coverage
- **Clinical Flagging**: Customizable thresholds for identifying concerning scores
- **Session Tracking**: Evaluate multiple tests and generate comprehensive reports
- **Professional Reports**: Export detailed Word documents for clinical records

## 🚀 Getting Started

### Prerequisites
```bash
Python 3.8+
pip install streamlit pandas numpy torch scipy python-docx
```

### Installation
1. Clone the repository
```bash
git clone https://github.com/MShia/normative-fixed-dash-jockeys.git
cd neuropsych-calculator
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Place your pre-trained models in the `models/` directory

4. Run the application
```bash
streamlit run app.py
```

## 📊 Supported Tests

- **DSF**: Digit Span Forward
- **DSB**: Digit Span Backward
- **SOC**: Speed of Comprehension
- **SDMT**: Symbol Digit Modalities

## 💡 How to Use

### Quick Workflow
1. **Enter Demographics** → Age, sex, and education in the sidebar
2. **Configure Test** → Select test type, enter raw score, set flag threshold
3. **Calculate** → Get instant percentile with confidence indicators
4. **Save & Continue** → Add to session for multiple test battery
5. **Generate Report** → Download comprehensive Word document

### Understanding Results

#### Percentile Interpretation
- **≥25th**: Within normal limits
- **16-24th**: Low average
- **5-15th**: Below average/Borderline
- **<5th**: Significantly below average

#### Agreement Confidence
- **Green (High/Moderate)**: Best method agrees with majority - reliable result
- **Red (Low)**: Best method disagrees with majority - interpret with caution

## 🔧 Model Structure

The calculator expects models in the following format:
```
models/
├── model_metadata.json
├── coverage_data.json
├── [test]_lr_model.pkl
├── [test]_lqr_q[00-98].pkl
├── [test]_nnqr_model.pth
└── [test]_scaler.pkl
```

## ⚖️ Clinical Considerations

This tool is designed for research and clinical support, not standalone diagnosis. Always consider:
- Full clinical presentation
- Test administration quality
- Patient effort and engagement
- Cultural and linguistic factors
- Corroborating assessments

## 🤝 Contributing

We welcome contributions! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [Streamlit](https://streamlit.io/) for seamless web deployment
- Statistical methods based on contemporary normative modeling research
- Icon design inspired by the intersection of neuroscience and data analytics

## ⚠️ Disclaimer

This application is intended primarily as a research tool for exploring and comparing normative modeling approaches. Users are advised to interpret results with caution and avoid relying solely on its outputs for critical clinical decisions. Final interpretation should always be guided by clinical expertise, corroborative assessments, and context-specific considerations.

---

**Questions?** Open an issue or contact the development team.

**Found it helpful?** Give us a ⭐ on GitHub!
