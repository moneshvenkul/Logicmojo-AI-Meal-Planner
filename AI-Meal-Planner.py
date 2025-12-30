import streamlit as st
from openai import OpenAI
import os
import base64
from streamlit_gsheets import GSheetsConnection
from pymongo import MongoClient
from datetime import datetime, timedelta
import pandas as pd
import bcrypt
import re
import secrets
import streamlit_cookies_manager as scm


st.set_page_config(
    page_title="AI Meal Planner",
    page_icon="🍽️",
    layout="centered"
)


# Authentication System
class AuthManager:
    def __init__(self, db_name="ai_meal_planner", collection_name="users"):
        self.db_name = db_name
        self.collection_name = collection_name
        self.tokens_collection = "auth_tokens"

    def get_mongo_client(self):
        """Return a MongoClient using Streamlit secrets or environment variable MONGODB_URI."""
        mongo_uri = None
        try:
            mongo_uri = st.secrets.get("MONGODB_URI")
        except Exception:
            pass
        if not mongo_uri:
            mongo_uri = os.environ.get("MONGODB_URI")
        if not mongo_uri:
            return None
        try:
            client = MongoClient(mongo_uri)
            client.admin.command('ping')
            return client
        except Exception:
            return None

    def hash_password(self, password):
        """Hash password using bcrypt."""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def verify_password(self, password, hashed):
        """Verify password against hash."""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

    def validate_email(self, email):
        """Validate email format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

    def validate_password(self, password):
        """Validate password strength."""
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        if not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r"[0-9]", password):
            return False, "Password must contain at least one digit"
        if not re.search(r"[!@#$%^&*()_+-=]", password):
            return False, "Password must contain at least one special character (!@#$%^&*()_+-=)"
        return True, "Password is valid"

    def user_exists(self, email):
        """Check if user exists."""
        client = self.get_mongo_client()
        if not client:
            return False
        try:
            db = client[self.db_name]
            users_collection = db[self.collection_name]
            return users_collection.find_one({"email": email}) is not None
        except Exception:
            return False
        finally:
            client.close()

    def register_user(self, username, email, password):
        """Register a new user."""
        if not self.validate_email(email):
            return False, "Invalid email format"

        is_valid, message = self.validate_password(password)
        if not is_valid:
            return False, message

        if self.user_exists(email):
            return False, "User with this email already exists"

        client = self.get_mongo_client()
        if not client:
            return False, "Database connection failed"

        try:
            db = client[self.db_name]
            users_collection = db[self.collection_name]

            user_data = {
                "username": username,
                "email": email,
                "password": self.hash_password(password),
                "created_at": datetime.now(),
                "is_active": True
            }

            users_collection.insert_one(user_data)
            return True, "User registered successfully"

        except Exception as e:
            return False, f"Registration failed: {str(e)}"
        finally:
            client.close()

    def authenticate_user(self, email, password):
        """Authenticate user credentials."""
        client = self.get_mongo_client()
        if not client:
            return False, "Database connection failed", None

        try:
            db = client[self.db_name]
            users_collection = db[self.collection_name]

            user = users_collection.find_one({"email": email, "is_active": True})
            if not user:
                return False, "Invalid email or password", None

            if self.verify_password(password, user["password"]):
                return True, "Login successful", {
                    "username": user["username"],
                    "email": user["email"],
                    "user_id": str(user["_id"])
                }
            else:
                return False, "Invalid email or password", None

        except Exception as e:
            return False, f"Authentication failed: {str(e)}", None
        finally:
            client.close()

    def generate_token(self, user_id, expiry_days=30):
        """Generate a secure session token for persistent login."""
        token = secrets.token_urlsafe(32)
        client = self.get_mongo_client()
        if not client:
            return None

        try:
            db = client[self.db_name]
            tokens_collection = db[self.tokens_collection]

            token_data = {
                "token": token,
                "user_id": user_id,
                "created_at": datetime.now(),
                "expires_at": datetime.now() + timedelta(days=expiry_days)
            }
            tokens_collection.insert_one(token_data)
            return token

        except Exception:
            return None
        finally:
            client.close()

    def validate_token(self, token):
        """Validate token and return user info if valid."""
        if not token:
            return None

        client = self.get_mongo_client()
        if not client:
            return None

        try:
            db = client[self.db_name]
            tokens_collection = db[self.tokens_collection]
            users_collection = db[self.collection_name]

            # Find token and check if it's not expired
            token_doc = tokens_collection.find_one({
                "token": token,
                "expires_at": {"$gt": datetime.now()}
            })

            if not token_doc:
                return None

            # Get user info
            from bson.objectid import ObjectId
            user = users_collection.find_one({
                "_id": ObjectId(token_doc["user_id"]),
                "is_active": True
            })

            if not user:
                return None

            return {
                "username": user["username"],
                "email": user["email"],
                "user_id": str(user["_id"])
            }

        except Exception:
            return None
        finally:
            client.close()

    def revoke_token(self, token):
        """Revoke/delete a session token."""
        if not token:
            return

        client = self.get_mongo_client()
        if not client:
            return

        try:
            db = client[self.db_name]
            tokens_collection = db[self.tokens_collection]
            tokens_collection.delete_one({"token": token})
        except Exception:
            pass
        finally:
            client.close()


def init_session_state():
    """Initialize session state variables for authentication."""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user_info' not in st.session_state:
        st.session_state.user_info = None
    if 'show_register' not in st.session_state:
        st.session_state.show_register = False
    if 'history' not in st.session_state:
        st.session_state.history = []
    if 'latest_plan' not in st.session_state:
        st.session_state.latest_plan = None
    if 'auth_token' not in st.session_state:
        st.session_state.auth_token = None


def show_login_form(auth_manager, cookies):
    """Display login form."""
    st.subheader("🔐 Login")

    with st.form("login_form"):
        email = st.text_input("Email", key="login_email", placeholder="Enter your email")
        password = st.text_input("Password", type="password", key="login_password", placeholder="Enter your password")
        remember_me = st.checkbox("Remember me for 30 days", value=True)

        col1, col2 = st.columns([1, 1])
        with col1:
            submit_button = st.form_submit_button("Login", use_container_width=True)

        if submit_button:
            if not email or not password:
                st.error("Please fill in all fields")
                return

            with st.spinner("Authenticating..."):
                success, message, user_info = auth_manager.authenticate_user(email, password)
                if success:
                    st.session_state.authenticated = True
                    st.session_state.user_info = user_info
                    
                    # Generate and store token if remember me is checked
                    if remember_me:
                        token = auth_manager.generate_token(user_info['user_id'])
                        if token:
                            st.session_state.auth_token = token
                            cookies['auth_token'] = token
                            cookies.save()
                    
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    st.divider()
    st.write("Don't have an account?")
    if st.button("🆕 Create New Account", use_container_width=True):
        st.session_state.show_register = True
        st.rerun()


def show_register_form(auth_manager):
    """Display registration form."""
    st.subheader("📝 Create Account")

    with st.form("register_form"):
        username = st.text_input("Username", key="register_username", placeholder="Choose a username")
        email = st.text_input("Email", key="register_email", placeholder="Enter your email")
        password = st.text_input("Password", type="password", key="register_password", placeholder="Create a strong password")
        confirm_password = st.text_input("Confirm Password", type="password", key="confirm_password", placeholder="Confirm your password")

        # Password strength indicator
        if password:
            is_valid, msg = auth_manager.validate_password(password)
            if is_valid:
                st.success("✅ Password meets requirements")
            else:
                st.warning(f"⚠️ {msg}")

        col1, col2 = st.columns([1, 1])
        with col1:
            submit_button = st.form_submit_button("Register", use_container_width=True)

        if submit_button:
            if not all([username, email, password, confirm_password]):
                st.error("Please fill in all fields")
                return

            if password != confirm_password:
                st.error("Passwords do not match")
                return

            with st.spinner("Creating account..."):
                success, message = auth_manager.register_user(username, email, password)
                if success:
                    st.success(message)
                    st.info("✅ Account created successfully! Please login with your new credentials")
                    st.session_state.show_register = False
                    st.rerun()
                else:
                    st.error(message)

    st.divider()
    st.write("Already have an account?")
    if st.button("🔐 Back to Login", use_container_width=True):
        st.session_state.show_register = False
        st.rerun()


def show_user_info(auth_manager, cookies):
    """Display user information and logout option."""
    if st.session_state.user_info:
        with st.sidebar:
            st.success(f"👋 Welcome, **{st.session_state.user_info['username']}**!")
            with st.expander("👤 Account Info", expanded=False):
                st.write(f"**Username:** {st.session_state.user_info['username']}")
                st.write(f"**Email:** {st.session_state.user_info['email']}")

            st.divider()
            if st.button("🚪 Logout", use_container_width=True):
                # Revoke token
                if st.session_state.auth_token:
                    auth_manager.revoke_token(st.session_state.auth_token)
                
                # Clear cookies
                if 'auth_token' in cookies:
                    del cookies['auth_token']
                    cookies.save()
                
                # Clear session state
                st.session_state.authenticated = False
                st.session_state.user_info = None
                st.session_state.show_register = False
                st.session_state.auth_token = None
                # Clear meal plan history on logout for security
                st.session_state.history = []
                st.session_state.latest_plan = None
                st.success("Logged out successfully!")
                st.rerun()


def require_authentication(auth_manager, cookies):
    """Main authentication flow with persistent login support."""
    init_session_state()

    # Wait for cookies to be ready before proceeding
    if not cookies.ready():
        st.stop()

    # Check for existing token in cookies if not already authenticated
    if not st.session_state.authenticated:
        stored_token = cookies.get('auth_token')
        if stored_token:
            # Try to authenticate with stored token
            user_info = auth_manager.validate_token(stored_token)
            if user_info:
                st.session_state.authenticated = True
                st.session_state.user_info = user_info
                st.session_state.auth_token = stored_token
                # Don't rerun here, just continue to show the app

    if not st.session_state.authenticated:
        st.title("🍽️ AI Meal Planner")
        st.write("**Create personalized meal plans with AI - Authentication Required**")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.session_state.show_register:
                show_register_form(auth_manager)
            else:
                show_login_form(auth_manager, cookies)

        return False
    else:
        show_user_info(auth_manager, cookies)
        return True


def get_current_user_id():
    """Get current user ID for database operations."""
    if st.session_state.authenticated and st.session_state.user_info:
        return st.session_state.user_info['user_id']
    return None


# Initialize OpenAI client (same as original)
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except (KeyError, AttributeError):
    try:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    except Exception:
        st.error("OpenAI API key not found. Please set it in Streamlit secrets or as an environment variable.")
        st.stop()


# Google Sheets functions (same as original)
WORKSHEET_NAME = "MealPlans"

def save_to_sheet(data):
    if not data:
        st.error("No data to save.")
        return False
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Add user information to the data
        user_info = st.session_state.user_info
        user_id = user_info['user_id'] if user_info else 'anonymous'
        username = user_info['username'] if user_info else 'anonymous'

        new_row = pd.DataFrame(
            [
                {
                    "Timestamp": timestamp,
                    "User ID": user_id,
                    "Username": username,
                    "Titles": data['title'],
                    "Calorie Goal": data['inputs']['kcal'],
                    "Ingredients Input": data['inputs']['ingredients'],
                    "Full Plan": data['content']
                }
            ]
        )

        try:
            existing_data = conn.read(worksheet=WORKSHEET_NAME, usecols=list(range(7)), ttl="5s")
            existing_data = existing_data.dropna(how="all")
        except Exception:
            existing_data = pd.DataFrame()

        updated_df = pd.concat([existing_data, new_row], ignore_index=True)
        conn.update(worksheet=WORKSHEET_NAME, data=updated_df)
        return True
    except Exception as e:
        st.error(f"An error occurred while saving to Google Sheets: {e}")
        return False


# MongoDB functions (updated to be user-specific)
def get_mongo_client():
    """Return a MongoClient using Streamlit secrets or environment variable MONGODB_URI."""
    mongo_uri = None
    try:
        mongo_uri = st.secrets.get("MONGODB_URI")
    except Exception:
        pass
    if not mongo_uri:
        mongo_uri = os.environ.get("MONGODB_URI")
    if not mongo_uri:
        return None
    try:
        client = MongoClient(mongo_uri)
        client.admin.command('ping')
        return client
    except Exception:
        return None


def save_to_mongo(data, db_name="ai_meal_planner", collection_name="meal_plans"):
    """Save the plan to MongoDB with user information."""
    if not data:
        st.error("No data to save.")
        return False

    user_id = get_current_user_id()
    if not user_id:
        st.error("User not authenticated")
        return False

    client = get_mongo_client()
    if not client:
        st.error("MongoDB URI not found or connection failed. Set MONGODB_URI in Streamlit secrets or environment variables.")
        return False
    try:
        db = client[db_name]
        coll = db[collection_name]
        doc = {
            "user_id": user_id,  # Add user_id to make data user-specific
            "username": st.session_state.user_info['username'],
            "timestamp": datetime.now(),
            "title": data['title'],
            "calorie_goal": data['inputs']['kcal'],
            "ingredients_input": data['inputs']['ingredients'],
            "exact_ingredients": data['inputs'].get('exact_ingredients', False),
            "extra": data['inputs'].get('extra'),
            "full_plan": data['content']
        }
        coll.insert_one(doc)
        return True
    except Exception as e:
        st.error(f"An error occurred while saving to MongoDB: {e}")
        return False


def load_from_mongo(limit=10, db_name="ai_meal_planner", collection_name="meal_plans"):
    """Load recent meal plans from MongoDB for the current user only."""
    user_id = get_current_user_id()
    if not user_id:
        return []

    client = get_mongo_client()
    if not client:
        return []
    try:
        coll = client[db_name][collection_name]
        # Only load plans for the current user
        cursor = coll.find({"user_id": user_id}).sort("timestamp", -1).limit(limit)
        entries = []
        for d in cursor:
            entry = {
                "title": d.get("title") or f"Plan {d.get('_id')}",
                "content": d.get("full_plan") or d.get("content") or "",
                "inputs": {
                    "ingredients": d.get("ingredients_input") or d.get("ingredients") or "",
                    "kcal": d.get("calorie_goal") or d.get("kcal") or 0,
                    "exact_ingredients": d.get("exact_ingredients", False),
                    "extra": d.get("extra") or None,
                }
            }
            entries.append(entry)
        return entries
    except Exception as e:
        st.error(f"Failed to load from MongoDB: {e}")
        return []


# Meal plan generation function (same as original)
def generate_meal_plan(ingredients, kcal=2000, exact_ingredients=False,
                       output_format='text', model='gpt-3.5-turbo',
                       system_role='You are a skilled cook with expertise of a chef.',
                       temperature=1, extra=None):
    prompt = f"""
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
"""
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


def set_background(image_path=None, image_url=None, opacity=0.65):
    """Apply a background image to the Streamlit app.
    - image_url: publicly accessible URL
    - image_path: local file path (will be base64-embedded)
    - opacity: overlay darkness (0.0 = transparent, 1.0 = solid white overlay)
    """
    try:
        if image_url:
            bg = image_url
        elif image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            ext = os.path.splitext(image_path)[1].lower()
            mime = "image/png" if ext in [".png"] else "image/jpeg"
            bg = f"data:{mime};base64,{data}"
        else:
            return  # no image provided

        overlay_alpha = 1.0 - float(opacity)
        css = f"""
        <style>
        .stApp {{
            background-image: url("{bg}");
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}
        /* subtle overlay to keep content readable */
        .stApp::before {{
            content: "";
            position: fixed;
            inset: 0;
            background: rgba(255,255,255,{overlay_alpha});
            pointer-events: none;
            z-index: 0;
        }}
        /* ensure main content sits above the overlay */
        .main .block-container, .css-1lcbmhc, .css-k1vhr4 {{
            position: relative;
            z-index: 1;
        }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"Background image not applied: {e}")


def set_bg_from_config(default_local="background.jpg"):
    """Try to set background from Streamlit secrets, env var, or a local file."""
    img_url = None
    try:
        img_url = st.secrets.get("BACKGROUND_IMAGE_URL")
    except Exception:
        pass
    if not img_url:
        img_url = os.environ.get("BACKGROUND_IMAGE_URL")

    if img_url:
        set_background(image_url=img_url, opacity=0.65)
        return

    # fallback to a local file in project root
    local_path = os.path.join(os.path.dirname(__file__), default_local)
    if os.path.exists(local_path):
        set_background(image_path=local_path, opacity=0.65)


# Main Application
def main():
    # Apply background (reads from Streamlit secrets 'BACKGROUND_IMAGE_URL',
    # env 'BACKGROUND_IMAGE_URL', or local 'background.jpg' next to this file)
    set_bg_from_config()

    # Initialize cookies manager
    cookies = scm.CookieManager()

    # Initialize authentication
    auth_manager = AuthManager()

    # Require authentication
    if not require_authentication(auth_manager, cookies):
        return

    # If authenticated, load user's history on first run
    if not st.session_state.history:
        try:
            loaded = load_from_mongo(limit=20)
            if loaded:
                st.session_state.history = loaded
                st.session_state.latest_plan = loaded[0] if loaded else None
        except Exception:
            pass

        # Hide the "Deploy" button, "Fork" app button, and other toolbar items
    hide_github_icon = """
        <style>
        /* Hide the Streamlit Cloud "Fork" & "Viewer" badges */
        .viewerBadge_container__1QSob,
        .styles_viewerBadge__1yB5_,
        .viewerBadge_link__1S137,
        .viewerBadge_text__1JaDK {
            display: none !important;
        }
        
        /* Hide the "Deploy" button */
        .stDeployButton {
            display: none;
        }
        
        /* OPTIONAL: Hide the hamburger menu (three dots) */
        #MainMenu {
            visibility: hidden;
        }
        
        /* OPTIONAL: Hide the footer "Made with Streamlit" */
        footer {
            visibility: hidden;
        }
        </style>
    """

    st.markdown(hide_github_icon, unsafe_allow_html=True)
    
    # Main app interface
    st.title("🍽️ AI Meal Planner")
    st.write(f"Welcome back, **{st.session_state.user_info['username']}**! Generate personalized meal plans based on your dietary preferences.")

    with st.form("meal_plan_form"):
        st.subheader("🥗 Your Ingredients and Preferences")
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
        submitted = st.form_submit_button("✨ Generate Meal Plan", use_container_width=True)

    if submitted:
        if not ingredients.strip():
            st.error("Please enter at least one ingredient.")
        else:
            with st.spinner("🤖 Generating your personalized meal plan..."):
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

    # Display latest plan
    if st.session_state.latest_plan:
        st.subheader("📋 Your AI-Generated Meal Plan")

        full_plan_text = st.session_state.latest_plan['content'] + "\n\n" + st.session_state.latest_plan['title']
        st.markdown(full_plan_text.replace('\n', '  \n'))

        if st.button("💾 Save Plan", use_container_width=True):
            with st.spinner("Saving your meal plan..."):
                saved = save_to_mongo(st.session_state.latest_plan)
                if saved:
                    st.success("✅ Plan saved successfully to your account!")
                else:
                    if save_to_sheet(st.session_state.latest_plan):
                        st.success("✅ Plan saved successfully to Google Sheets!")
                    else:
                        st.error("❌ Failed to save plan. Please try again.")

    # Sidebar history
    st.sidebar.title("📜 Your Generation History")
    if st.sidebar.button("🔄 Refresh from Database"):
        with st.spinner("Loading from database..."):
            loaded = load_from_mongo(limit=50)
            if loaded:
                st.session_state.history = loaded
                st.session_state.latest_plan = loaded[0] if loaded else None
                st.success(f"✅ Loaded {len(loaded)} plans from your account.")
            else:
                st.info("No plans found in database.")

    if st.sidebar.button("🗑️ Clear History"):
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


if __name__ == "__main__":
    main()