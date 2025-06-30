import csv
import os
import base64
import logging
import requests
import csv
from datetime import datetime
from openai import OpenAI
import re
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from PIL import Image
from io import BytesIO
import time
import random
import shutil 

from config import (
    OPENAI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    INDEXNOW_API_KEY,
    AI_TOPICS_DIRECTORY,
    CSV_FILE_LIST_OF_NEW_TOPICS,
    CSV_FILE_LIST_OF_ARCHIVED_TOPICS,
    CSV_FILE_LIST_OF_ARCHIVED_AFFILIATE_TOPICS,
    CSV_FILE_LIST_OF_ERROR_TOPICS,
    FILE_PATH_NEW_TOPICS,
    FILE_PATH_ARCHIVED_TOPICS,
    FILE_PATH_ERROR_TOPICS,
    FILE_PATH_ARCHIVED_AFFILIATE_TOPICS,
    AI_IMAGES_DIRECTORY,
    AI_ARTICLES_DIRECTORY,
    LOG_FULL_PATH,
    WEBSITE_URL,
    WEBSITE_TITLE,
    WEBSITE_DESCRIPTION,
    WEBSITE_KEYWORDS,
    WEBSITE_AUDIENCE,
    WEBSITE_LANGUAGE,
    CURRENT_DATE,
    AFFILIATE_CONTENT_DIRECTORY
)

# Ensure the affiliate content directory exists
os.makedirs(AFFILIATE_CONTENT_DIRECTORY, exist_ok=True)

# Set up logging.
# The logging configuration checks if LOG_FULL_PATH is set. 
# If it is not set, logging is configured to use the default settings, which log to the console. 
# This ensures that the script continues to run even if LOG_FULL_PATH is empty.
if LOG_FULL_PATH:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename=LOG_FULL_PATH, filemode='a')
else:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logging.info("✅ Script started...")

def load_prompt(file_path):
    try:
        with open(file_path, 'r') as file:
            return file.read()
    except FileNotFoundError:
        logging.error(f"❌ Prompt file not found: {file_path}")
        raise
    except Exception as e:
        logging.error(f"❌ Error loading prompt file: {file_path}. Error: {e}")
        raise

def check_env_variable_error(var_name):
    value = os.getenv(var_name)
    if not value:
        logging.error(f"❌ [Environment Variable Error] {var_name} is missing! Please set it as an environment variable.")
        raise ValueError(f"❌ [Environment Variable Error] {var_name} is missing! Please set it as an environment variable.")
    else:
        logging.info(f"✅ [Environment Variable Loaded] {var_name} successfully loaded")
        logging.debug(f"✅ [Environment Variable Loaded] {var_name} successfully loaded with value: {value[:4]}***")
    return value

def check_env_variable_warning(var_name):
    value = os.getenv(var_name)
    if not value:
        logging.warning(f"⚠️ [Environment Variable Warning] {var_name} is missing! Please set it as an environment variable.")
        return None
    else:
        logging.info(f"✅ [Environment Variable Loaded] {var_name} successfully loaded")
        logging.debug(f"✅ [Environment Variable Loaded] {var_name} successfully loaded with value: {value[:4]}***")
    return value

def initialize_csv(file_path):
    try:
        if not os.path.exists(file_path):
            with open(file_path, 'w', newline='') as file:
                logging.info(f"✅ [CSV Initialization] Created new CSV file: {file_path}")
        else:
            logging.debug(f"✅ [CSV Initialization] CSV file already exists: {file_path}")
    except PermissionError:
        logging.critical(f"❌ [CSV Initialization Error] Permission denied: Unable to create or access the file at {file_path}. Check file permissions.")
    except FileNotFoundError:
        logging.error(f"❌ [CSV Initialization Error] File not found: The directory for {file_path} does not exist. Ensure the directory is created.")
    except Exception as e:
        logging.error(f"❌ [CSV Initialization Error] Unexpected error while initializing CSV file: {file_path}. Error: {e}")

def write_to_csv(file_path, article_url, topic_idea, description):
    try:
        with open(file_path, 'a', newline='') as outfile:
            writer = csv.writer(outfile, quoting=csv.QUOTE_ALL)
            writer.writerow([article_url, topic_idea, description])
        logging.info(f"✅ [CSV Write] Article URL: '{article_url}', Topic: '{topic_idea}', Description: '{description}' successfully written to file: {file_path}")
    except Exception as e:
        logging.error(f"❌ [CSV Write Error] Error writing to file {file_path}: {e}")


def retry_with_backoff(func, max_retries=3, initial_delay=1, backoff_factor=2, *args, **kwargs):
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"⚠️ [Retry] Attempt {attempt + 1} failed. Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= backoff_factor
            else:
                logging.error(f"❌ [Retry] All {max_retries} attempts failed. Last error: {e}")
                raise

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("⚠️ [Telegram Warning] Telegram message not sent due to missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
        return

    message = f"{WEBSITE_URL}\n{message}"  # Add the website to the message

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}

    def send_request():
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            logging.info(f"✅ [Telegram] Message sent successfully to chat ID: {TELEGRAM_CHAT_ID}")
        else:
            raise Exception(f"Failed to send message. Status code: {response.status_code}, Response: {response.text}")

    retry_with_backoff(send_request)

def get_topics_create_csv_and_notify():
    prompt = load_prompt("AI_scripts/prompts/generate_topics.txt").format(
        WEBSITE_URL=WEBSITE_URL,
        WEBSITE_TITLE=WEBSITE_TITLE,
        WEBSITE_DESCRIPTION=WEBSITE_DESCRIPTION,
        WEBSITE_KEYWORDS=WEBSITE_KEYWORDS,
        WEBSITE_AUDIENCE=WEBSITE_AUDIENCE,
        WEBSITE_LANGUAGE=WEBSITE_LANGUAGE
    )
    client = OpenAI(
            api_key=OPENAI_API_KEY,  # Pass the api_key directly
        )    
    response = client.chat.completions.create(
    model="gpt-4.1",
    messages=[
            {"role": "system", "content": f"You are a helpful assistant. You MUST respond in {WEBSITE_LANGUAGE}."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1500,
        # The max_tokens parameter controls the length of the generated output 
        # by specifying the maximum number of tokens the model is allowed to produce.
        n=1,
        # The n parameter specifies how many different completion choices the model should generate. 
        # By setting n=1, the function instructs the model to produce only one completion choice for the given input. 
        # This is useful when you want a single, straightforward response without additional alternatives.
        temperature=0.7,
        # The temperature parameter controls the randomness of the output.
        # A value of 0.7 is chosen to balance creativity and coherence.
        frequency_penalty=0.1,  
        # frequency_penalty reduces the likelihood of the model repeating the same lines/words.
        # Example value, range: -2.0 to 2.0
        # For generating topic ideas, using small positive values (e.g., 0.2–0.6) for both can help increase variety and reduce repetition, which is usually desirable.
        # Too high values may make the output less relevant or more random.
        presence_penalty=0.4    
        # presence_penalty increases the likelihood of the model introducing new topics.
        # Example value, range: -2.0 to 2.0
        # For generating topic ideas, using small positive values (e.g., 0.2–0.6) for both can help increase variety and reduce repetition, which is usually desirable.
        # Too high values may make the output less relevant or more random.
    )
    topics = response.choices[0].message.content.strip()
    logging.info(topics)
    
    # Write topics to the CSV file
    with open(FILE_PATH_NEW_TOPICS, 'a', newline='') as file:
        writer = csv.writer(file, quoting=csv.QUOTE_ALL)
        for line in topics.split('\n'):
            # Split the line into fields, handling quoted strings properly
            fields = [f.strip().replace('""', '"') for f in line.strip().strip('"').split('","')]
            writer.writerow(fields)
    
    if topics:
        logging.info("✅ Topics were written to CSV file.")
        send_telegram_message("New topics have been generated and saved.")
    else:
        logging.error("❌ Failed to generate 10 topics.")
    
    return topics

def fetch_topic_and_description():
    with open(FILE_PATH_NEW_TOPICS, 'r') as infile:
        reader = csv.reader(infile)
        lines = list(reader)

    if not lines:
        logging.info("🔄 CSV is empty, generating new topics...")
        get_topics_create_csv_and_notify()
        return fetch_topic_and_description() # recursive call to fetch the new topics

    try:
        topic_data = lines[0]
        if len(topic_data) == 1:
            affiliate_item_id = topic_data[0]
            affiliate_url = None
            topic_idea = None
            description = None
            content_type = "affiliate"
        elif len(topic_data) == 2:
            topic_idea, description = topic_data
            content_type = "article"
            affiliate_url = None
            affiliate_item_id = None
        else:
            raise ValueError("Line does not contain exactly 1 or 2 values.")
    except ValueError as e:
        content_type = handle_invalid_csv_line(lines, topic_data, e)
        return fetch_topic_and_description()  # recursive call to fetch the
    
    if content_type == "affiliate":
        logging.info(f"🌐 Content type is affiliate for ID: {affiliate_item_id}")
        affiliate_folder = os.path.join(AFFILIATE_CONTENT_DIRECTORY, affiliate_item_id)

        # List all files in the affiliate_folder
        files_in_affiliate_folder = os.listdir(affiliate_folder)
        logging.info(f"Files in affiliate folder: {files_in_affiliate_folder}")

        # Load the affiliate product info text
        affiliate_text_path = os.path.join(AFFILIATE_CONTENT_DIRECTORY, affiliate_item_id , affiliate_item_id + ".txt")
        with open(affiliate_text_path, 'r', encoding='utf-8') as f:
            affiliate_text = f.read()

        try:
            with open(affiliate_text_path, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
            if first_line.startswith("http://") or first_line.startswith("https://"):
                affiliate_url = first_line
            else:
                raise ValueError(f"❌ Invalid affiliate URL in first line of {affiliate_text_path}: {first_line}")
        except Exception as e:
            logging.error(f"❌ Error reading affiliate URL from {affiliate_text_path}: {e}")
            raise

        # Prepare prompt for OpenAI
        # Load the prompt template and format placeholders first
        prompt_template = load_prompt("AI_scripts/prompts/generate_affiliate_idea_topic.txt").format(
            WEBSITE_URL=WEBSITE_URL,
            WEBSITE_TITLE=WEBSITE_TITLE,
            WEBSITE_DESCRIPTION=WEBSITE_DESCRIPTION,
            WEBSITE_KEYWORDS=WEBSITE_KEYWORDS,
            WEBSITE_AUDIENCE=WEBSITE_AUDIENCE,
            WEBSITE_LANGUAGE=WEBSITE_LANGUAGE
        )

        # Combine prompt and affiliate product info
        prompt = prompt_template + "\n\nProduct Information:\n" + affiliate_text
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
            {"role": "system", "content": f"You are a helpful assistant. You MUST respond in {WEBSITE_LANGUAGE}."},
            {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            n=1,
            temperature=0.7,
            )

            # Extract topic idea and description from the response
            response_text = response.choices[0].message.content.strip()
            # Expect response in format: "topic_idea","description"
            match = re.match(r'"([^"]*)","([^"]*)"', response_text)
            if match:
                topic_idea = match.group(1).strip()
                description = match.group(2).strip()
                logging.info(f"✅ [Affiliate Content] Generated topic idea: '{topic_idea}' and description: '{description}' for affiliate ID: {affiliate_item_id}")
                send_telegram_message(f"✅ Affiliate content generated for ID: {affiliate_item_id}. Topic: '{topic_idea}', Description: '{description}'")
            else:
                logging.error(f"❌ Response format unexpected: {response_text}")
                topic_idea = "Default Topic Idea"
                description = "Default Description"
                send_telegram_message(f"❌ Failed to extract topic idea and description for affiliate ID: {affiliate_item_id}. Using default values.")

        except Exception as e:
            logging.error(f"❌ OpenAI request failed while generating description and topic for affiliate ID: {affiliate_item_id}. Error: {e}")
            topic_idea = "none"
            description = "none"
            send_telegram_message(f"❌ OpenAI request failed while generating description and topic for affiliate ID: {affiliate_item_id}. Using default values. Error: {e}")

        # Store the affiliate URL for later use
        global CURRENT_AFFILIATE_URL
        CURRENT_AFFILIATE_URL = affiliate_url
        logging.info(f"✅ Affiliate URL set for ID {affiliate_item_id}: {affiliate_url}")
        
        topic_data = [affiliate_item_id, affiliate_url]
        
        return topic_idea, description, content_type, affiliate_item_id

    elif content_type == "article":
        logging.info(f"🌐 Content type is article")
        return topic_idea, description, content_type, None
    
    else:
        # Remove the used line
        logging.error(f"❌ THERE'S SOMETHING WRONG")
        return None, None, content_type, None

def handle_invalid_csv_line(lines, topic_data, e):
    logging.error(f"❌ Invalid CSV format: {e}")
        # Move the invalid line to the ERROR topics file
    with open(FILE_PATH_ERROR_TOPICS, 'a', newline='') as error_file:
        error_file.write(','.join(str(item) if item is not None else '' for item in topic_data) + '\n')
    logging.info(f"✅ Invalid line moved to ERROR topics: {topic_data}")
    content_type = "error"
        # Notify via Telegram about the line error
    send_telegram_message(f"❌ Invalid line detected in topics CSV: {topic_data}. Moved to ERROR topics.")

    # Remove the invalid line
    with open(FILE_PATH_NEW_TOPICS, 'w', newline='') as outfile:
        writer = csv.writer(outfile)
        writer.writerows(lines[1:])
    return content_type

def get_image_create_file_and_notify(topic_idea, description):
    prompt = load_prompt("AI_scripts/prompts/generate_image.txt").format(
            WEBSITE_URL=WEBSITE_URL,
            WEBSITE_TITLE=WEBSITE_TITLE,
            WEBSITE_DESCRIPTION=WEBSITE_DESCRIPTION,
            WEBSITE_KEYWORDS=WEBSITE_KEYWORDS,
            WEBSITE_AUDIENCE=WEBSITE_AUDIENCE,
            WEBSITE_LANGUAGE=WEBSITE_LANGUAGE,
            topic_idea=topic_idea, 
            description=description
        )
    logging.info(f"🔄 Requesting to generate the image")

    def generate_image():
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size='1024x1024',  # other options '256x256', '512x512', '1024x1024', '1024x1792', '1792x1024'
        )
        return response.data[0].url

    try:
        image_url = retry_with_backoff(generate_image)
        logging.info(f"✅ [Image Generation] Generated Image URL: {image_url}")

        def download_image():
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                return response.content
            else:
                raise Exception(f"Failed to download image. Status code: {response.status_code}")

        image_content = retry_with_backoff(download_image)

        sanitized_topic = CURRENT_DATE + "_" + topic_idea.replace(' ', '_').replace("'", "")
        original_image_path = os.path.join(AI_IMAGES_DIRECTORY, f"{sanitized_topic}_1024x1024.png")
        with open(original_image_path, 'wb') as image_file:
            image_file.write(image_content)
        logging.info(f"✅ [Image Download] Original image downloaded and saved to {original_image_path}")

        # Resize the image
        with Image.open(BytesIO(image_content)) as original_image:
            resized_dimensions = (512, 512)  # Change dimensions as required
            resized_image = original_image.resize(resized_dimensions)

            # Save the resized image
            resized_image_path = os.path.join(AI_IMAGES_DIRECTORY, f"{sanitized_topic}.png")
            resized_image.save(resized_image_path)
            logging.info(f"✅ [Image Resize] Resized image saved to {resized_image_path}")

        return resized_image_path
    except Exception as e:
        logging.error(f"❌ [Image Generation Error] Failed to generate or download the image. Error: {e}")
        return None
    
def generate_image_alt_text(topic_idea, description, image_path):
    try:
        with open(image_path, "rb") as image_file:
            img_base64 = base64.b64encode(image_file.read()).decode('utf-8')

        # Load prompt template and format with variables
        prompt_template = load_prompt("AI_scripts/prompts/generate_image_alt_text.txt")
        prompt = prompt_template.format(
            WEBSITE_URL=WEBSITE_URL,
            WEBSITE_TITLE=WEBSITE_TITLE,
            WEBSITE_DESCRIPTION=WEBSITE_DESCRIPTION,
            WEBSITE_KEYWORDS=WEBSITE_KEYWORDS,
            WEBSITE_AUDIENCE=WEBSITE_AUDIENCE,
            WEBSITE_LANGUAGE=WEBSITE_LANGUAGE,
            topic_idea=topic_idea,
            description=description
        )

        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_base64}",
                                "detail": "low",
                            },
                        },
                    ],
                }
            ],
            max_tokens=100,
            n=1,
            temperature=0.5,
        )

        image_alt_text = response.choices[0].message.content.strip()
        image_alt_text = image_alt_text.replace("Alt Text: ", "").replace("alt text: ", "").replace('"', '').replace("'", "").strip()

        logging.info(f"✅ Generated alt text: {image_alt_text} for image: {os.path.basename(image_path)}")
        return image_alt_text

    except Exception as e:
        logging.error(f"❌ Error generating alt text for image {image_path}: {e}")
        return "Alt text generation failed."

def notify_indexnow(article_url):
    indexnow_servers = [
        "https://api.indexnow.org/indexnow",
        "https://www.bing.com/indexnow",
        "https://searchadvisor.naver.com/indexnow",
        "https://search.seznam.cz/indexnow",
        "https://yandex.com/indexnow",
        "https://indexnow.yep.com/indexnow"
    ]

    def notify_server(server_url):
        full_url = f"{server_url}?url={article_url}&key={INDEXNOW_API_KEY}"
        response = requests.get(full_url, timeout=10)
        if response.status_code == 200:
            logging.info(f"✅ [IndexNow] Successfully notified {server_url} for URL: {article_url}")
        else:
            raise Exception(f"Request to {server_url} failed. Status code: {response.status_code}, Response: {response.text}")

    for server_url in indexnow_servers:
        try:
            retry_with_backoff(notify_server, server_url=server_url)
        except Exception as e:
            logging.error(f"❌ [IndexNow Error] Failed to notify {server_url}. Error: {e}")

    return True

def get_article_content(topic_idea, description, image_path, content_type, affiliate_article_id):
    if content_type == "affiliate":
        logging.info("✅ Content type is affiliate, generating affiliate article...")
        affiliate_folder = os.path.join(AFFILIATE_CONTENT_DIRECTORY, affiliate_article_id)

        # Get the image file (assuming only one image file exists)
        image_files = [f for f in os.listdir(affiliate_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        if not image_files:
            logging.error(f"❌ No image file found in {affiliate_folder}")
            return None

        original_image_file = image_files[0]
        original_image_path = os.path.join(affiliate_folder, original_image_file)

        # Prepare sanitized topic and paths with original extension
        sanitized_topic = CURRENT_DATE + "_" + topic_idea.replace(' ', '_').replace("'", "")
        original_ext = os.path.splitext(original_image_file)[1]  # e.g. '.jpg', '.png'
        sanitised_original_image_path = os.path.join(AI_IMAGES_DIRECTORY, f"{sanitized_topic}_original{original_ext}")
        resized_image_path = os.path.join(AI_IMAGES_DIRECTORY, f"{sanitized_topic}{original_ext}")

        # Copy original image to AI_IMAGES_DIRECTORY with sanitized name
        try:
            shutil.copy2(original_image_path, sanitised_original_image_path)
            logging.info(f"✅ Original image copied to {sanitised_original_image_path}")
        except Exception as e:
            logging.error(f"❌ Failed to copy original image: {e}")

        # Resize the image to 500px width, maintaining aspect ratio, save resized copy
        try:
            with Image.open(sanitised_original_image_path) as img:
                w_percent = (500 / float(img.width))
                h_size = int((float(img.height) * float(w_percent)))
                resized_img = img.resize((500, h_size), Image.LANCZOS)
                resized_img.save(resized_image_path)
                logging.info(f"✅ Resized affiliate image saved to {resized_image_path}")
        except Exception as e:
            logging.error(f"❌ Failed to resize affiliate image {resized_image_path}: {e}")

        image_url = f"{WEBSITE_URL}{resized_image_path}"
        # Generate alt text for the image
        image_alt_text = generate_image_alt_text(topic_idea, description, resized_image_path)

        # Get all other files (e.g., PDFs)
        other_files = [f for f in os.listdir(affiliate_folder) if not f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.txt'))]
        other_file_urls = {other_file: f"{WEBSITE_URL}{affiliate_folder}/{other_file}" for other_file in other_files}

        # Load the affiliate URL
        affiliate_url = CURRENT_AFFILIATE_URL

        logging.info(f"🔄 Requesting OpenAI to generate affiliate content for topic: {topic_idea}")

        # Load the prompt
        prompt = load_prompt("AI_scripts/prompts/generate_affiliate_article.txt").format(
            WEBSITE_URL=WEBSITE_URL,
            WEBSITE_TITLE=WEBSITE_TITLE,
            WEBSITE_DESCRIPTION=WEBSITE_DESCRIPTION,
            WEBSITE_KEYWORDS=WEBSITE_KEYWORDS,
            WEBSITE_AUDIENCE=WEBSITE_AUDIENCE,
            WEBSITE_LANGUAGE=WEBSITE_LANGUAGE,
            topic_idea=topic_idea,
            description=description,
            image_url=image_url,
            image_alt_text=image_alt_text,
            other_file_urls=other_file_urls,
            affiliate_url=affiliate_url
        )

        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
            {"role": "system", "content": f"You are a helpful assistant. You MUST respond in {WEBSITE_LANGUAGE}."},
            {"role": "user", "content": prompt}
            ],
            max_tokens=3500,
            n=1,
            temperature=0.7,
            frequency_penalty=0.1
        )

        article_content = response.choices[0].message.content.strip()
        logging.info(f"✅ [Affiliate Content] Generated Article content: {article_content}")
        article_content = article_content.replace('```markdown', '').replace('```', '').replace('``', '').replace('"""', '"').replace('""', '"').strip()


        # Apply the same filename logic as for generic articles
        sanitized_topic = topic_idea.replace(' ', '_').replace("'", "").replace('"', '')  # Remove quotes
        article_file_path = os.path.join(AI_ARTICLES_DIRECTORY, f"""{CURRENT_DATE}-{topic_idea.replace(' ', '_').replace('"', '').replace(",", '').replace(".", '').replace("'", '')}.md""")
        with open(article_file_path, 'w') as article_file:
            article_file.write(article_content)
        logging.info(f"✅ Article for '{topic_idea}' created and saved to {article_file_path}")

        return article_file_path
    else:
        # Generate alt text for the image
        image_alt_text = generate_image_alt_text(topic_idea, description, image_path)
        logging.info(f"✅ Generated alt text: {image_alt_text}")

        logging.info(f"🔄 Requesting OpenAI to generate article content for topic: {topic_idea}")
        prompt = load_prompt("AI_scripts/prompts/generate_article.txt").format(
            WEBSITE_URL=WEBSITE_URL,
            WEBSITE_TITLE=WEBSITE_TITLE,
            WEBSITE_DESCRIPTION=WEBSITE_DESCRIPTION,
            WEBSITE_KEYWORDS=WEBSITE_KEYWORDS,
            WEBSITE_AUDIENCE=WEBSITE_AUDIENCE,
            WEBSITE_LANGUAGE=WEBSITE_LANGUAGE,
            topic_idea=topic_idea,
            description=description,
            image_path=image_path,
            image_alt_text=image_alt_text
        )
        client = OpenAI(api_key=OPENAI_API_KEY)    
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": f"You are a helpful assistant. You MUST respond in {WEBSITE_LANGUAGE}."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3500,
            n=1,
            temperature=0.7,
            frequency_penalty=0.1
        )
        article_content = response.choices[0].message.content.strip()

        article_content = article_content.replace('```markdown', '').replace('```', '').replace('``', '').replace('"""', '"').replace('""', '"').strip()
        
        lines = article_content.split('\n')
        if lines[0].strip() == '':
            lines = lines[1:]
        article_content = '\n'.join(lines)

        article_file_path = os.path.join(AI_ARTICLES_DIRECTORY, f"""{CURRENT_DATE}-{topic_idea.replace(' ', '_').replace('"', '').replace(",", '').replace(".", '').replace("'", '')}.md""")
        with open(article_file_path, 'w') as article_file:
            article_file.write(article_content)
        logging.info(f"✅ Article for '{topic_idea}' created and saved to {article_file_path}")

        return article_file_path

def check_and_load_env_variables():
    logging.info("🔍 Checking environment variables...")
    OPENAI_API_KEY = check_env_variable_error("OPENAI_API_KEY")
    TELEGRAM_BOT_TOKEN = check_env_variable_warning("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = check_env_variable_warning("TELEGRAM_CHAT_ID")
    INDEXNOW_API_KEY = check_env_variable_warning("INDEXNOW_API_KEY")
    return OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, INDEXNOW_API_KEY

def ensure_directories_exist(*directories):
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logging.info(f"✅ Ensured directory exists: {directory}")
    return directories

def initialize_files(*file_paths):
    for file_path in file_paths:
        initialize_csv(file_path)
    return file_paths

def create_article_with_image():
    exception_count = 0  # Counter to track the number of exceptions
    max_exceptions = 3  # Maximum number of allowed exceptions

    while exception_count < max_exceptions:
        logging.info("🔄 Fetch the next topic idea and description...")
        # Fetch the next topic idea and description
        topic_data = fetch_topic_and_description()

        if len(topic_data) == 4:
            topic_idea, description, content_type, affiliate_article_id = topic_data
        else:
            logging.error("❌ Invalid topic data format. Expected 4 elements, got: {len(topic_data)}")

        logging.info(f"✅ Topic Idea: {topic_idea}, Description: {description}, Content Type: {content_type}, ID: {affiliate_article_id}.")

        try:
            if content_type == "affiliate":
                logging.info("✅ Content type is affiliate, skipping image generation...")
                image_path = None  # No image path needed for affiliate content
            elif content_type == "article":
                logging.info("🔄 Use the topic idea and description to request an image...")
                # Use the topic idea and description to request an image
                image_path = get_image_create_file_and_notify(topic_idea, description)

                # Check if image generation failed
                if not image_path:
                    raise Exception(f"Image generation failed for topic '{topic_idea}'. Moving to error topics.")
            else:
                logging.error(f"❌ Invalid content type: {content_type}. Expected 'affiliate' or 'article', got: {content_type}")
                raise ValueError(f"Invalid content type: {content_type}")  

            logging.info("🔄 Request the article content...")
            # Request the article content
            article_file_path = get_article_content(topic_idea, description, image_path, content_type, affiliate_article_id)

            # Construct article URL and notify via Telegram & IndexNow here (at the end of create_article_with_image)

            with open(article_file_path, 'r') as file:
                article_content = file.read()

            # Extract categories from the front matter
            categories_match = re.search(r'categories: \[(.*?)\]', article_content)
            if categories_match:
                categories = [category.strip() for category in categories_match.group(1).split(',')]
                categories = [category.replace(' ', '%20').replace('&', '%26') for category in categories]
                category_path = '/'.join(categories).lower()
            else:
                category_path = "articles"  # default fallback if categories extraction fails
                logging.warning("⚠️ Categories extraction failed. Defaulted to /articles.")

            # Construct URL for your blog's format
            article_url = f"{WEBSITE_URL}{category_path}/{CURRENT_DATE.replace('-', '/')}-{topic_idea.replace(':', '-').replace(' ', '_')}.html"

            # Replace single quotes with an empty string as required
            article_url = article_url.replace("'", '')

            send_telegram_message(f"New article for '{topic_idea}' has been generated and saved. Read it here: {article_url}")
            logging.info(f"✅ New article for '{topic_idea}' has been generated and saved. Read it here: {article_url}")

            if INDEXNOW_API_KEY:
                notify_indexnow(article_url)
            else:
                logging.warning("⚠️ No INDEXNOW_API_KEY found. IndexNow notification will not be sent.")

            # Add the topic idea and description to the archived topics file
            write_to_csv(FILE_PATH_ARCHIVED_TOPICS, article_url, topic_idea, description)
            logging.info("✅ Added topic idea and description to archived topics file.")

            if content_type == "affiliate":
                # Add the affiliate article ID to the archived topics file
                write_to_csv(FILE_PATH_ARCHIVED_AFFILIATE_TOPICS, article_url, affiliate_article_id, CURRENT_AFFILIATE_URL)
                logging.info(f"✅ Added affiliate article ID {affiliate_article_id} to archived topics file.")

            logging.info("🔄 Remove the used line from the new topics file...")
            # Remove the used line from the new topics file
            with open(FILE_PATH_NEW_TOPICS, 'r') as new_file:
                lines = new_file.readlines()

            with open(FILE_PATH_NEW_TOPICS, 'w', newline='') as new_file:
                new_file.writelines(lines[1:])

            logging.info(f"✅ Topic '{topic_idea}' archived and removed from new topics.")



            break  # Exit the loop if successful

        except Exception as e:
            exception_count += 1  # Increment the exception counter
            logging.error(f"❌ Error occurred: {e}")

            handle_invalid_csv_line(lines, topic_data, e)

            # Send a Telegram message about the error
            send_telegram_message(f"❌ Error occurred while processing topic '{topic_idea}'. Moved to ERROR topics. Error: {e}")
            logging.error(f"❌ Error occurred while processing topic '{topic_idea}'. Moved to ERROR topics. Error: {e}")

            # Continue to the next topic
            logging.info(f"🔄 Retrying with a new topic. Attempt {exception_count}/{max_exceptions}")

    if exception_count >= max_exceptions:
        logging.error(f"❌ Maximum number of exceptions ({max_exceptions}) reached. Stopping the process.")
        send_telegram_message(f"❌ Maximum number of exceptions ({max_exceptions}) reached. Stopping the process.")
def main():
    OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, INDEXNOW_API_KEY = check_and_load_env_variables()
    ensure_directories_exist(AI_TOPICS_DIRECTORY, AI_IMAGES_DIRECTORY, AI_ARTICLES_DIRECTORY)
    
    # Ensure the files are created if they don't exist
    initialize_csv(FILE_PATH_NEW_TOPICS)
    initialize_csv(FILE_PATH_ARCHIVED_TOPICS)
    initialize_csv(FILE_PATH_ERROR_TOPICS)
    initialize_csv(FILE_PATH_ARCHIVED_AFFILIATE_TOPICS)
   
    # REQUESTING THE ARTICLE!!!
    logging.info("🔄 Initializing OpenAI requests...")
    create_article_with_image() 
    

    logging.info("✅ Script completed!")

if __name__ == "__main__":
    main()