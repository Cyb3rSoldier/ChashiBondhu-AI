# 🌾 ChashiBondhu AI

### Smarter Farming. Better Markets. Less Food Waste.

**ChashiBondhu AI** is an AI-powered agricultural decision-support and marketplace platform designed to help Bangladeshi farmers make informed farming and selling decisions. By combining crop suitability recommendations, weather insights, buyer-demand analysis, and Bangla/Banglish voice assistance, the project aims to connect agricultural production with real market opportunities.

Building on our existing farmer-to-consumer marketplace, ChashiBondhu AI aims to improve market access, reduce unsold produce, and support a more efficient and sustainable food supply chain.

> **Project Track:** Smart Food Chain  
> **Secondary Impact Area:** Food Waste Zero  
> **Competition:** International AI Builders Congress 2026

---

## 🎯 Problem Statement

Smallholder farmers in Bangladesh face several challenges throughout the agricultural value chain:

- **Limited agricultural guidance:** Access to reliable, localized crop and seasonal information can be difficult.
- **Weather uncertainty:** Changing weather conditions make farming decisions more challenging.
- **Uncertain market demand:** Farmers may struggle to understand which crops buyers need and when demand is strongest.
- **Dependence on intermediaries:** Limited direct access to buyers can weaken farmers' bargaining power.
- **Food waste:** Delayed sales and unsold harvests can lead to produce loss and reduced income.
- **Digital accessibility:** Complex interfaces and language barriers can make digital agricultural services difficult to use.

These challenges show the need for a platform that connects farming decisions with actual market opportunities.

## 💡 Our Solution

ChashiBondhu AI combines AI-assisted farming guidance with a direct farmer-to-consumer marketplace.

The platform aims to help farmers understand what they can grow, consider local weather and agricultural conditions, identify potential buyers, and sell their harvest more effectively.

### ✨ Key Features

#### 🌱 1. AI Crop Advisor
- Recommends potentially suitable crops based on location, season, soil or land conditions, water availability, and verified agricultural guidance.
- Considers buyer-demand signals when comparing suitable crop options.
- Explains recommendations in simple language.

#### 🌦️ 2. Weather-Aware Farming Support
- Integrates relevant weather information to support farming decisions.
- Provides crop-relevant alerts and guidance when reliable data is available.
- Uses historical climate data for analysis, while keeping historical patterns separate from actual weather forecasts.

#### 🛒 3. Demand-Linked Marketplace
- Connects farmers directly with consumers and potential buyers.
- Allows farmers to list expected harvest dates and quantities.
- Uses marketplace demand signals to help farmers identify potential selling opportunities.

#### 🗣️ 4. Bangla and Banglish Voice Assistance
- Aims to make agricultural information easier to access through natural-language questions.
- Supports a simple, farmer-friendly experience with potential voice input and spoken responses.
- Prioritizes understandable guidance for users with limited digital experience.

#### ♻️ 5. Surplus Produce Management
- Helps identify unsold or surplus produce.
- Supports matching available produce with interested buyers.
- Explores farmer-approved discounts and alternative selling opportunities to reduce food loss.

*Feature availability depends on implementation progress. Planned features are not presented as completed functionality.*

## 🧠 How AI Fits In

AI is intended to support practical decisions rather than simply provide a chatbot.

The planned recommendation engine combines several factors:

- **Weather and seasonal suitability**
- **Agricultural and land-condition suitability**
- **Buyer demand**
- **Indicative economic considerations**

Candidate crops should first pass basic suitability checks. Market demand must not override essential agricultural requirements.

The system can use a transparent scoring approach to rank suitable options, with recommendations explained to the farmer. Any scoring weights and agricultural rules will require validation using reliable data and qualified agricultural expertise.

A language model may help communicate verified information in accessible Bangla or Banglish. Important agricultural claims should be grounded in trusted sources rather than generated without verification.

## 🏗️ Planned Technology Stack

| Component | Technology |
|---|---|
| Existing web application | PHP, JavaScript |
| Frontend styling | HTML, Tailwind CSS |
| Database | MySQL |
| AI and data analysis | Python, pandas, scikit-learn |
| AI service API | FastAPI |
| Language assistance | LLM API and retrieval-augmented generation (RAG) |
| Weather and climate data | Relevant weather APIs and NASA POWER |
| Agricultural knowledge | Verified agricultural guidance and extension resources |

The existing PHP/MySQL marketplace will remain the foundation. A separate Python service can provide crop scoring, data analysis, and AI-assisted functionality as development progresses.

*The technology stack describes the current foundation and planned integrations; not every component is necessarily implemented yet.*

## 📊 Data Sources

Potential sources for the project include:

- **Bangladesh Meteorological Department (BMD):** Weather forecasts and warnings, subject to data availability and access.
- **NASA POWER:** Historical and near-real-time meteorological and solar data for climate analysis. It is not a substitute for a future weather forecast.
- **Department of Agricultural Extension (DAE), Bangladesh:** Agricultural guidance and crop-related resources.
- **ChashiBondhu marketplace database:** Available product listings, orders, buyer requests, and other demand signals.
- **Local market information:** Verified crop prices and market demand data where accessible.

Data quality, location coverage, update frequency, and usage conditions must be checked before integrating each source.

## 🔄 How It Works

1. A farmer provides basic information such as location, available land, water resources, and intended planting period.
2. The system evaluates candidate crops using available agricultural and seasonal information.
3. Suitable options are compared with relevant buyer-demand signals.
4. The farmer receives understandable recommendations and supporting explanations.
5. Farmers can list available or expected produce on the marketplace.
6. The platform helps identify interested buyers and potential opportunities for surplus produce.
7. Project performance is evaluated using recommendation quality, buyer matching, selling time, and food-loss indicators.

## 📈 Expected Impact

ChashiBondhu AI aims to contribute to:

- Better-informed crop planning.
- Improved access to direct buyers.
- More efficient connections between production and demand.
- Reduced unsold and spoiled produce.
- Better access to understandable agricultural information.
- A more transparent and sustainable food supply chain.

We intend to evaluate these outcomes through measurable indicators, including:

- Buyer-matching rate.
- Median time required to sell produce.
- Quantity of unsold or spoiled produce.
- Farmer revenue and documented production or selling costs.
- Crop recommendation quality, reviewed against reliable agricultural guidance.
- Usability and task-completion rates for Bangla and voice-based interactions.

**Impact figures will only be reported as real-world results when supported by collected evidence. Simulations and estimates will be clearly labeled.**

## 🚀 Development Roadmap

- [ ] Review and document the existing ChashiBondhu marketplace.
- [ ] Validate farmer and buyer needs through interviews.
- [ ] Select an initial pilot area and a small set of crops.
- [ ] Prepare reliable agricultural, weather, and marketplace data.
- [ ] Build a transparent crop-suitability recommendation engine.
- [ ] Integrate relevant weather information.
- [ ] Connect buyer-demand signals to crop and selling decisions.
- [ ] Develop Bangla/Banglish AI assistance.
- [ ] Explore voice input and spoken responses.
- [ ] Implement surplus-produce matching.
- [ ] Test recommendations and usability with real users.
- [ ] Evaluate outcomes and prepare a demonstrable prototype.

## 🛠️ Getting Started

The project builds on an existing PHP/MySQL marketplace. Setup instructions will be updated to match the repository's actual structure and implemented services.

### Prerequisites

- PHP and Composer
- MySQL or MariaDB
- A local development environment such as XAMPP
- Node.js and npm, if required by the frontend build process
- Python, if the AI service has been added

### Installation

1. Clone the repository:

   ```bash
   git clone <YOUR_REPOSITORY_URL>
   ```

2. Move into the project directory:

   ```bash
   cd ChashiBondhu-AI
   ```

3. Configure your local PHP and MySQL environment.

4. Import the project's database schema or SQL file, if included in the repository.

5. Update the database connection settings using your local configuration.

6. Start the application using the instructions appropriate to the current project structure.

*Exact installation commands, environment variables, database setup, and AI-service instructions will be documented as the implementation is finalized.*

## 🤝 Contributing

Contributions, feedback, and ideas are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make and test your changes.
4. Submit a pull request describing the improvement.

Please avoid committing passwords, API keys, database credentials, or other sensitive configuration.

## 🔐 Responsible AI

- Recommendations should be based on relevant data and verified agricultural guidance.
- The platform should communicate uncertainty and avoid unsupported claims about yield, profit, or crop disease.
- Personal and marketplace data should be handled responsibly.
- Farmers should remain in control of their planting and selling decisions.
- Real-world impact claims must be supported by evidence.

**Project:** ChashiBondhu AI

**Competition:** International AI Builders Congress 2026

**ChashiBondhu AI — Connecting farmers, agricultural knowledge, and market opportunities.** 🌾
