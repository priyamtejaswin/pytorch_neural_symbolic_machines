Captures progress, todos and issues.
===

# Adding support for WikiSQL
1. Get/download/setup data.
2. Write code to convert table to KG, as in [Compositional Semantic Parsing on Semi-Structured Tables](https://www.aclweb.org/anthology/P15-1142.pdf), Section 4.
3. Add the extra pre-processing steps from *this* repo:
> We revised the data pre-processing script, and re-processed the WikiTableQuestions dataset. We also turned off the --anonymize_datetime_and_number_entities option when preprocessing the dataset, which gave better performance.
5. Add a new agent/env for WikiSQL, if required.
6. Update the encoder -- BERT, TaBERT will take too much time. Go back to LSTM encoders.

**Extra credits**
1. See how agents and envs are implemented and integrated with OpenAI Gym.


## 1. Data and setup
Data repo: [WikiSQL](https://github.com/salesforce/WikiSQL)