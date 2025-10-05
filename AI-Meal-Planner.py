import streamlit as st
from openai import OpenAI
import os
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import pandas as pd

st.set_page_config(
    page_title="AI Meal Planner",
    page_icon="🍽️",
    layout="centered"
)

try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except (KeyError, AttributeError):
    try:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    except Exception:
        st.error("OpenAI API key not found. Please set it in Streamlit secrets or as an environment variable.")
        st.stop()

if 'history' not in st.session_state:
    st.session_state.history = []
if 'latest_plan' not in st.session_state:
    st.session_state.latest_plan = None

WORKSHEET_NAME = "MealPlans"

def save_to_sheet(data):
    if not data:
        st.error("No data to save.")
        return False
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        new_row = pd.DataFrame(
            [
                {
                    "Timestamp": timestamp,
                    "Titles": data['title'],
                    "Calorie Goal": data['inputs']['kcal'],
                    "Ingredients Input": data['inputs']['ingredients'],
                    "Full Plan": data['content']
                }
            ]
        )

        try:
            existing_data = conn.read(worksheet=WORKSHEET_NAME, usecols=list(range(5)), ttl="5s")
            existing_data = existing_data.dropna(how="all")
        except Exception:
            existing_data = pd.DataFrame()

        updated_df = pd.concat([existing_data, new_row], ignore_index=True)
        conn.update(worksheet=WORKSHEET_NAME, data=updated_df)
        return True
    except Exception as e:
        st.error(f"An error occurred while saving to Google Sheets: {e}")
        return False

def generate_meal_plan(ingredients, kcal=2000, exact_ingredients=False,
                       output_format='text', model='gpt-3.5-turbo',
                       system_role='You are a skilled cook with expertise of a chef.',
                       temperature=1, extra=None):
    prompt = f'''
Create a healthy daily meal plan for breakfast, lunch, and dinner based on the following ingredients: ```{ingredients}```
Your output should be in the {output_format} format.

### Instructions:
1. {'Use ONLY the provided ingredients with salt, pepper, and spices.' if exact_ingredients else 'Feel free to incorporate other common pantry staples.'}
2. Specify the exact amount of each ingredient.
3. Ensure that the total daily calorie intake is below {kcal}.
4. For each meal, explain each recipe step-by-step in clear sentences.
5. For each meal, specify the total calories and the number of servings.
6. For each meal, provide a concise, descriptive title.
7. For each recipe, indicate the prep, cook and total time.
{'8. If possible the meals should be: ' + extra if extra else ''}
9. Separate the recipes with 50 dashes.
The last line of your answer must be a string containing ONLY the titles of the recipes separated by a comma.
Example: '\nBroccoli and Egg Scramble, Grilled Chicken and Vegetable, Baked Fish and Cabbage Slaw'.
'''
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': system_role},
                {'role': 'user', 'content': prompt}
            ],
            temperature=temperature
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"An error occurred while generating the meal plan: {e}")
        return None

st.title("AI Meal Planner 🍽️")
st.write("Generate personalized meal plans based on your dietary preferences and restrictions.")

with st.form("meal_plan_form"):
    st.subheader("Your Ingredients and Preferences")
    ingredients = st.text_area(
        "List your available ingredients (one per line)",
        "Chicken breast\nBrown rice\nBroccoli\nSpinach\nOlive oil\nGarlic\nOnion",
        height=150, help="Enter one ingredient per line."
    )
    kcal = st.number_input(
        "Maximum daily calorie goal (kcal)",
        min_value=1000, max_value=5000, value=2000, step=50,
        help="Set your target for daily caloric intake."
    )
    col1, col2 = st.columns(2)
    with col1:
        exact_ingredients = st.checkbox("Use ONLY these ingredients?", value=True, help="If checked, the AI will not use common pantry staples.")
    with col2:
        extra = st.text_input("Extra requirements?", placeholder="e.g., gluten-free, vegetarian")
    submitted = st.form_submit_button("✨ Generate Meal Plan")

if submitted:
    if not ingredients.strip():
        st.error("Please enter at least one ingredient.")
    else:
        with st.spinner("Generating your meal plan..."):
            meal_plan = generate_meal_plan(
                ingredients=ingredients, kcal=kcal,
                exact_ingredients=exact_ingredients, extra=extra
            )
        if meal_plan:
            try:
                *plan_body, titles_line = meal_plan.strip().split('\n')
                plan_title = titles_line.strip()
                plan_content = '\n'.join(plan_body).strip()
            except ValueError:
                plan_title = f"Plan based on {ingredients.splitlines()[0]}"
                plan_content = meal_plan

            history_entry = {
                "title": plan_title,
                "content": plan_content,
                "inputs": {
                    "ingredients": ingredients, "kcal": kcal,
                    "exact_ingredients": exact_ingredients, "extra": extra,
                }
            }
            st.session_state.latest_plan = history_entry
            st.session_state.history.insert(0, history_entry)
            st.rerun()

if st.session_state.latest_plan:
    st.subheader("Your AI-Generated Meal Plan")
    
    full_plan_text = st.session_state.latest_plan['content'] + "\n\n" + st.session_state.latest_plan['title']
    st.markdown(full_plan_text.replace('\n', '  \n'))

    if st.button("💾 Save Plan to Google Sheet"):
        with st.spinner("Saving..."):
            if save_to_sheet(st.session_state.latest_plan):
                st.success("Plan saved successfully to your Google Sheet!")

st.sidebar.title("📜 Generation History")
if st.sidebar.button("Clear History"):
    st.session_state.history = []
    st.session_state.latest_plan = None
    st.rerun()

if not st.session_state.history:
    st.sidebar.info("Your generated meal plans will appear here.")
else:
    for i, entry in enumerate(st.session_state.history):
        with st.sidebar.expander(f"**{entry['title']}**"):
            st.markdown(entry['content'].replace('\n', '  \n'))
            st.caption(
                f"Kcal: {entry['inputs']['kcal']}, "
                f"Strict Ingredients: {'Yes' if entry['inputs']['exact_ingredients'] else 'No'}"
            )

