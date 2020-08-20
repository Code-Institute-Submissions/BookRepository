import logging
from logging.handlers import RotatingFileHandler
import os
import json
from flask import Flask, render_template_string, render_template, redirect, url_for, request, flash, session
from flask_mongoengine import MongoEngine, MongoEngineSession, MongoEngineSessionInterface
from flask_user import login_required, UserManager, UserMixin, current_user, roles_required
from flask_login import logout_user
import datetime
from datetime import timedelta
import requests
from flask_debugtoolbar import DebugToolbarExtension

from config import ConfigClass

from dotenv import load_dotenv
from pathlib import Path
env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path)


# --- // Application Factory Setup (based on the Flask-User example for MongoDB)
# Setup Flask and load app.config
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config.from_object(__name__ + ".ConfigClass")
# app.debug = True


# Initialise rotating file logging in Development, not on Heroku
# Set after app initialisation
if os.environ.get("ENABLE_FILE_LOGGING"):
    logging.basicConfig(
        handlers=[RotatingFileHandler("./logs/book_repository.log", maxBytes=100000, backupCount=10)],
        level=os.environ.get("LOGGING_LEVEL"),
        format="%(name)s - %(levelname)s - %(message)s"
    )
else:
    # Initialize logging to console, works on Heroku
    app.logger.setLevel(logging.os.environ.get("LOGGING_LEVEL"))

# Setup Flask-MongoEngine --> MongoEngine --> PyMongo --> MongoDB
db = MongoEngine(app)

# Use Flask Sessions with Mongoengine
app.session_interface = MongoEngineSessionInterface(db)

# Initiate the Flask Debug Toolbar Extension
toolbar = DebugToolbarExtension(app)


# --- // Classes -> MongoDB Collections: User, Book, Genre.
class User(db.Document, UserMixin):
    # Active set to True to allow login of user
    active = db.BooleanField(default=True)

    # User authentication information
    username = db.StringField(default="")
    password = db.StringField()

    # User information
    first_name = db.StringField(default="")
    last_name = db.StringField(default="")
    email = db.StringField(default="")
    email_confirmed_at = db.DateTimeField()
    # Required for the e-mail confirmation, and subsequent login.

    # Relationships  (Roles: user or user and Admin)
    roles = db.ListField(db.StringField(), default=["user"])

    meta = {
        "auto_create_index": True,
        "index_background": True,
        "indexes": ["username"]
    }


class Book(db.Document):
    title = db.StringField(default="", maxlength=250)
    author = db.StringField(default="", maxlength=250)
    year = db.IntField(maxlength=4)
    ISBN = db.IntField(maxlength=13)
    short_description = db.StringField(default="", maxlength=2000)
    user = db.StringField(required=True)
    creation_date = db.DateTimeField(default=datetime.datetime.now)
    comments = db.StringField(default="", maxlength=3500)
    rating = db.IntField(choices=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    genre = db.StringField(default="")
    private_view = db.StringField(default="off")
    book_thumbnail = db.StringField(default="")

    meta = {
        "auto_create_index": True,
        "index_background": True,
        "indexes": ["title"],
        "ordering": ["title"]
    }


class Genre(db.Document):
    genre = db.StringField(default="")
    icon = db.StringField(default="")
    description = db.StringField(default="")

    meta = {
        "auto_create_index": True,
        "index_background": True,
        "indexes": ["genre"],
        "ordering": ["genre"]
    }


# Setup Flask-User and specify the User data-model
user_manager = UserManager(app, db, User)


# --- // Book Repository Main Routes (Endpoints): CRUD.
@app.route("/")
@app.route("/index")
@app.route("/index.html")
def home_page():
    # Landing/Home Page, accessible before signing/logging in.
    if current_user.is_authenticated:
        return redirect(url_for("member_page"))

    # Create admin user as first/default user, if admin does not exist.
    # Password and e-mail are set using environment variables.
    if not User.objects.filter(User.username == "admin"):
        app.logger.info(
            "Admin user is created on application startup if user does not exist.")
        user = User(
            username="admin",
            first_name="Administrator",
            last_name="Administrator",
            email=os.environ.get("MAIL_DEFAULT_SENDER"),
            email_confirmed_at=datetime.datetime.utcnow(),
            password=user_manager.hash_password(os.environ.get("ADMIN_PASSWORD"))
        )
        user.roles.append("Admin")
        user.save()

    # Create the Genre Collection if it does not exist. Taken from
    # https://bookriot.com/guide-to-book-genres/
    # The genre.json file contains the genre collection in JSON format and is
    # used to  create the genre collection in the Book Repository (MongoDB).
    if not Genre.objects():
        try:
            with open("genre.json", "r", encoding="utf-8") as f:
                genre_array = json.load(f)
        except FileNotFoundError:
            flash("Genre file can't be found. The filename is 'genre.json' and contains the 32 Book Genres.","danger")

        try:
            genre_instances = [Genre(**data) for data in genre_array]
            Genre.objects.insert(genre_instances, load_bulk=False)
            flash("Genres Collection successfully created.", "success")
            app.logger.info("Initial load of the Genre Collection to the Book Repository successful (index.html). Endpoint: home_page.")
        except BaseException:
            flash("Genres Collection NOT created.", "danger")
            app.logger.warning("Initial load of the Genre Collection to the Book Repository failed (index.html). Endpoint: home_page.")
        finally:
            render_template("index.html")

    return render_template("index.html")


@app.route("/members")
@app.route("/members/<int:page>")
@login_required
def member_page(page=1):
    # The "R" in CRUD, a virtual library or stack of books to browse.
    app.logger.info(f"{current_user.username} is accessing the Member's Page (members.html). Endpoint: member_page.")

    books_pagination = Book.objects.filter(user=current_user.username).paginate(page=page, per_page=7)
    return render_template("members.html", books_pagination=books_pagination, page_prev=(page - 1), page_next=(page + 1))


@app.route("/add_book")
@login_required
def add_book():
    # Preparing for the "C" in CRUD, filling in the add book form.
    app.logger.info(f"{current_user.username} is adding a book (add_book.html) by filling out the add book form. Endpoint: add_book.")
    genre = Genre.objects()
    return render_template("add_book.html", genre=genre)


@app.route("/save_book", methods=["POST"])
@login_required
def save_book():
    # The "C" in CRUD, save the filled in add book form.
    book = Book(
        title=request.form.get("title"),
        author=request.form.get("author"),
        year=request.form.get("year"),
        ISBN=request.form.get("isbn"),
        user=current_user.username,
        short_description=request.form.get("short_description"),
        comments=request.form.get("comments"),
        rating=request.form.get("rating"),
        genre=request.form.get("genre"),
        private_view=request.form.get("private_view")
    )

    payload = {}
    isbn_key = f"isbn:{book.ISBN}"
    payload["q"] = isbn_key
    payload["key"] = os.environ.get("GOOGLE_API_KEY")

    try:
        book_request = requests.get("https://www.googleapis.com/books/v1/volumes", params=payload, headers={'User-agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:61.0) Gecko/20100101 Firefox/61.0'})
        book_thumbnail_w_http = book_request.json()["items"][0]["volumeInfo"]["imageLinks"]["thumbnail"]
        book_thumbnail_w_https = book_thumbnail_w_http.replace("http://", "https://")
        book.book_thumbnail = book_thumbnail_w_https
        app.logger.info(f"{current_user.username} has successfully requested the thumbnail image {book.book_thumbnail} for the book {book.title} with the id {book.id} (add_book.html). Endpoint: save_book.")
    except BaseException:
        book.book_thumbnail = "/static/images/BR_logo_no_thumbnail.png"
        app.logger.warning(f"{current_user.username} has not successfully requested the thumbnail image for the book {book.title} with the id {book.id} (add_book.html). Endpoint: save_book.")

    try:
        book.save()
        flash(f"The book {book.title} was saved!", "success")
        app.logger.info(f"{current_user.username} is saving the book {book.title} with the id {book.id} (add_book.html). Endpoint: save_book.")
    except BaseException:
        app.logger.warning(f"{current_user.username} did not succeed in saving the {book.title} (add_book.html). Endpoint: save_book.")
        flash(f"The book {book.title} was NOT saved!", "danger")
    return redirect(url_for("member_page"))


@app.route("/edit_book/<book_id>")
@login_required
def edit_book(book_id):
    # Preparing for the "U" in CRUD, updating the book form fields.
    book = Book.objects.get(id=book_id)
    genre = Genre.objects()
    app.logger.info(f"{current_user.username} is updating the book {book.title} with the id {book.id} (edit_book.html). Endpoint: edit_book.")
    return render_template("edit_book.html", book=book, genre=genre)


@app.route("/update_book/<book_id>", methods=["POST"])
@login_required
def update_book(book_id):
    # The "U" in CRUD, saving the changes made to the update book form fields.
    book = Book.objects.get(id=book_id)
    fields = {
        "title": request.form.get("title"),
        "author": request.form.get("author"),
        "year": request.form.get("year"),
        "ISBN": request.form.get("isbn"),
        "short_description": request.form.get("short_description"),
        "comments": request.form.get("comments"),
        "rating": request.form.get("rating"),
        "genre": request.form.get("genre"),
        "private_view": request.form.get("private_view")
    }

    if fields["private_view"] != "on":
        fields["private_view"] = "off"

    payload = {}
    isbn_field = fields["ISBN"]
    isbn_key = f"isbn:{isbn_field}"
    payload["q"] = isbn_key
    payload["key"] = os.environ.get("GOOGLE_API_KEY")

    try:
        book_request = requests.get("https://www.googleapis.com/books/v1/volumes", params=payload, headers={'User-agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:61.0) Gecko/20100101 Firefox/61.0'})
        book_thumbnail_w_http = book_request.json()["items"][0]["volumeInfo"]["imageLinks"]["thumbnail"]
        book_thumbnail_w_https = book_thumbnail_w_http.replace("http://", "https://")
        fields["book_thumbnail"] = book_thumbnail_w_https
        app.logger.info(f"{current_user.username} has successfully requested the thumbnail image {book.book_thumbnail} for the book {book.title} with the id {book.id} (add_book.html). Endpoint: save_book.")
    except BaseException:
        fields["book_thumbnail"] = "/static/images/BR_logo_no_thumbnail.png"
        app.logger.warning(f"{current_user.username} has not successfully requested the thumbnail image for the book {book.title} with the id {book.id} (add_book.html). Endpoint: save_book.")

    try:
        book.update(**fields)
        flash(f"The book {book.title} is updated!", "success")
        app.logger.info(f"{current_user.username} updated the book {book.title} with the id {book.id} (edit_book.html). Endpoint: update_book.")
    except BaseException:
        app.logger.warning(f"{current_user.username} did not update the book {book.title} with the id {book.id} (edit_book.html). Endpoint: update_book.")
        flash(f"The book {book.title} was NOT updated!", "danger")
    return redirect(url_for("member_page"))


@app.route("/delete_book/<book_id>")
@login_required
def delete_book(book_id):
    # The "D" in CRUD, deleting the book based on 'id' after delete modal
    # confirmation.
    book = Book.objects.get(id=book_id)
    try:
        book.delete()
        flash(f"The book {book.title} is deleted!", "success")
        app.logger.info(f"{current_user.username} deleted the book {book.title} with the id {book.id} (members.html). Endpoint: delete_book.")
    except BaseException:
        flash(f"The book {book.title} was NOT deleted!", "danger")
        app.logger.warning(f"{current_user.username} did not delete the book {book.title} with the id {book.id} (members.html). Endpoint: delete_book.")
    return redirect(url_for("member_page"))


@app.route("/search_book")
@login_required
def search_book():
    # Preparing for the book search in Book Repository, filling in the search
    # book form.
    genre = Genre.objects()
    app.logger.info(f"{current_user.username} is filling out the book search form. (search_book.html). Endpoint: search_book.")
    return render_template("search_book.html", genre=genre)


@app.route("/save_search", methods=["GET", "POST"])
@login_required
def save_search():
    # Save the search book results in a session cookie, to use by
    # 'search_results' repeatedly to display the paginated search results.
    fields = {
        "title": request.form.get("title"),
        "author": request.form.get("author"),
        "year": request.form.get("year"),
        "ISBN": request.form.get("isbn"),
        "short_description": request.form.get("short_description"),
        "comments": request.form.get("comments"),
        "rating": request.form.get("rating"),
        "genre": request.form.get("genre"),
        "private_view": request.form.get("private_view")
    }
    session["fields"] = fields

    app.logger.info(f"{current_user.username} is searching (saving search in session cookie) for books matching {fields} (search_results.html). Endpoint: save_search.")

    return redirect(url_for("search_results"))


@app.route("/administration", methods=["GET", "POST"])
@roles_required("Admin")
def administration():

    return render_template_string("Administration Page")


@app.route("/search_results", methods=["GET", "POST"])
@app.route("/search_results/<int:page>")
@login_required
def search_results(page=1):
    # Book search using a combination of form fields saved in the session
    # cookie in 'save_search', and based on the values in some key fields
    # decide which Book Repository BaseQuerySet to run.
    fields = session.get("fields")

    form_title = fields["title"]
    form_author = fields["author"]
    try:
        form_isbn = int(fields["ISBN"])
    except ValueError:
        form_isbn = 0
    except TypeError:
        form_isbn = 0
    try:
        form_rating = int(fields["rating"])
    except ValueError:
        form_rating = 1
    except TypeError:
        form_rating = 0
    form_genre = fields["genre"]
    form_private_view = fields["private_view"]

    # Query Book Repository based on the search form data
    # Private Search "form_private_view == "on"
    if form_private_view == "on":
        if form_isbn:
            book_query_results = Book.objects.filter(user=current_user.username, ISBN=form_isbn).paginate(page=page, per_page=7)
            app.logger.info(f"{current_user.username} found books matching {book_query_results} - 1: Private & ISBN Search (search_results.html). Endpoint: search_results.")
            return render_template("search_results.html", book_query_results=book_query_results, page_prev=(page - 1), page_next=(page + 1))
        elif form_genre is None:
            book_query_results = Book.objects.filter(user=current_user.username, title__icontains=form_title, author__icontains=form_author, rating__gte=form_rating).order_by("+title", "+author", "-rating").paginate(page=page, per_page=7)
            app.logger.info(f"{current_user.username} found books matching {book_query_results} - 2: Private, no Genre, no ISBN, Title, Author, and Rating Search (search_results.html). Endpoint: search_results.")
            return render_template("search_results.html", book_query_results=book_query_results, page_prev=(page - 1), page_next=(page + 1))
        else:
            book_query_results = Book.objects.filter(user=current_user.username, title__icontains=form_title, author__icontains=form_author, rating__gte=form_rating, genre=form_genre).order_by("+title", "+author", "-rating").paginate(page=page, per_page=7)
            app.logger.info(f"{current_user.username} found books matching {book_query_results} - 3: Private, no ISBN, Title, Author, Rating, and Genre Search (search_results.html). Endpoint: search_results.")
            return render_template("search_results.html", book_query_results=book_query_results, page_prev=(page - 1), page_next=(page + 1))
    # Public Search "form_private_view == None"
    else:
        if form_isbn:
            book_query_results = Book.objects.filter(ISBN=form_isbn, private_view="off").paginate(page=page, per_page=7)
            app.logger.info(f"{current_user.username} found books matching {book_query_results} - 4: Public & ISBN Search (search_results.html). Endpoint: search_results.")
            return render_template("search_results.html", book_query_results=book_query_results, page_prev=(page - 1), page_next=(page + 1))
        elif form_genre is None:
            book_query_results = Book.objects.filter(title__icontains=form_title, author__icontains=form_author, rating__gte=form_rating, private_view="off").order_by("+title", "+author", "-rating").paginate(page=page, per_page=7)
            app.logger.info(f"{current_user.username} found books matching {book_query_results} - 5: Public, no Genre, no ISBN, Title, Author, and Rating Search (search_results.html). Endpoint: search_results.")
            return render_template("search_results.html", book_query_results=book_query_results, page_prev=(page - 1), page_next=(page + 1))
        else:
            book_query_results = Book.objects.filter(title__icontains=form_title, author__icontains=form_author, rating__gte=form_rating, genre=form_genre, private_view="off").order_by("+title", "+author", "-rating").paginate(page=page, per_page=7)
            app.logger.info(f"{current_user.username} found books matching {book_query_results} - 6: Public, no ISBN, Title, Author, Rating, and Genre Search (search_results.html). Endpoint: search_results.")
            return render_template("search_results.html", book_query_results=book_query_results, page_prev=(page - 1), page_next=(page + 1))


@app.route("/delete_user")
@login_required
def delete_user():
    # Delete user, user initiated, from edit_user_profile.html. "D" in CRUD.
    deleted_user = current_user.username
    find_user_books = Book.objects.filter(user=current_user.username)
    find_user = User.objects.filter(username=current_user.username)

    try:
        logout_user()
        find_user_books.delete()
        find_user.delete()
        flash(f"We're sad to see you go {deleted_user}!", "success")
        app.logger.warning(f"{deleted_user} is has left the Book Repository (delete_user.html). Endpoint: delete_user.")
    except:
        flash(f"Your account is still alive and active {find_user.username}!", "danger")
        app.logger.warning(f"{deleted_user} is still alive and active on the Book Repository (delete_user.html). Endpoint: delete_user.")
    return redirect(url_for("home_page"))


# --- // Admin Dashboard for user management and content loading (genre and book collections).
@app.route("/admin_dashboard")
@app.route("/admin_dashboard/<int:page>")
@roles_required("Admin")
def admin_dashboard(page=1):
    # Admin Dashboard for user management, loading genres and sample books, and display statistics.
    user_details_query = User.objects().order_by("username").paginate(page=page, per_page=10)
    user_details_query_count = User.objects.count()
    book_list = Book.objects()
    book_list_count = book_list.count()

    genre_dict = {}
    for book in book_list:
        if book.genre in genre_dict:
            genre_dict[f"{book.genre}"] += 1
        else:
            genre_dict[f"{book.genre}"] = 1
    tuple_in_right_order = sorted(genre_dict.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    return render_template("admin_dashboard.html", user_details_query=user_details_query, page_prev=(page - 1), page_next=(page + 1), user_details_query_count=user_details_query_count, book_list_count=book_list_count, tuple_in_right_order=tuple_in_right_order)


@app.route("/update_user/<user_id>", methods=["POST"])
@roles_required("Admin")
def update_user(user_id):
    # The "U" in CRUD, saving the changes made to the update user modal form fields.
    user = User.objects.get(id=user_id)
    user_form_name = user.username
    admin_user_form = {
        "active": request.form.get("active"),
        "email": request.form.get(f"email_{user_form_name}"),
        "first_name": request.form.get(f"first_name_{user_form_name}"),
        "last_name": request.form.get(f"last_name_{user_form_name}"),
        "password": request.form.get(f"password_{user_form_name}")
    }

    # Paranoia: make sure admin account can't be set to inactive, even though the form does not allow it, 
    # however the URL can be created and used anyway.
    if user.username == "admin":
        admin_user_form["active"] = True
    elif admin_user_form["active"] == "on":
        admin_user_form["active"] = True
    else:
        admin_user_form["active"] = False

    # Validate the password, checking the password to confirm password fields match = no update.
    if request.form.get(f"password_{user_form_name}") != request.form.get(f"password_conf_{user_form_name}"):
        flash(f"Passwords did not match for {user.username}, please try again!", "danger")
        return redirect(url_for("admin_dashboard"))

    # Checking if the password is accidentally changed (the current hash) and the current/original/unchanged 
    # hashed password ($2b$) = set to original/current password.
    if admin_user_form["password"] == user.password and admin_user_form["password"].startswith("$2b$"):
        admin_user_form["password"] == user.password
    else:
        admin_user_form["password"] = user_manager.hash_password(admin_user_form["password"])

    user.update(**admin_user_form)
    flash(f"User {user.username} profile updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin_delete_user/<user_id>", methods=["GET"])
@roles_required("Admin")
def admin_delete_user(user_id):
    # The "D" in CRUD, deleting the user based on 'id' after delete modal
    # with NO confirmation.
    user = User.objects.get(id=user_id)
    user_books = Book.objects.filter(user=user.username)

    if user.username != "admin":
        deleted_username = user.username
        try:
            user_books.delete()
            user.delete()
            flash(f"The user {deleted_username} is deleted!", "success")
            app.logger.info(f"{current_user.username} deleted the user {deleted_username} (admin_dashboard.html). Endpoint: admin_delete_user.")
        except BaseException:
            flash(f"The user {deleted_username} was NOT deleted!", "danger")
            app.logger.warning(f"{current_user.username} did not delete the user {deleted_username} (admin_dashboard.html). Endpoint: admin_delete_user.")
    return redirect(url_for("admin_dashboard"))


@app.route("/load_genres")
@roles_required("Admin")
def load_genres():
    # Create the Genre Collection if it does not exist. Taken from
    # https://bookriot.com/guide-to-book-genres/
    if not Genre.objects():
        try:
            with open("genre.json", "r", encoding="utf-8") as f:
                genre_array = json.load(f)
        except FileNotFoundError:
            flash("Genre file can't be found. The filename is 'genre.json' and contains the 32 Book Genres.", "danger")

        try:
            genre_instances = [Genre(**data) for data in genre_array]
            Genre.objects.insert(genre_instances, load_bulk=False)
            flash(f"Genres Collection successfully created.", "success")
            app.logger.info(f"{current_user.username} has successfully loaded the Genre Collection to the Book Repository (admin_dashboard.html). Endpoint: load_genres.")
        except BaseException:
            flash(f"Genres Collection NOT created.", "danger")
            app.logger.warning(f"{current_user.username} has NOT loaded the Genre Collection to the Book Repository (admin_dashboard.html). Endpoint: load_genres.")
        finally:
            return redirect(url_for("admin_dashboard") or url_for("home_page"))
    else:
        flash(f"Genres Collection already created.", "info")
        return redirect(url_for("admin_dashboard"))


@app.route("/load_books")
@roles_required("Admin")
def load_books():
    # Create the sample Book Collection if it does not exist.
    if not Book.objects():
        try:
            with open("book.json", "r", encoding="utf-8") as f:
                book_dict = json.load(f)
        except FileNotFoundError:
            flash("Book file can't be found. The filename is 'book.json' and contains 15 sample Books.", "danger")

        try:
            book_instances = [Book(**data) for data in book_dict]
            Book.objects.insert(book_instances, load_bulk=False)
            flash(f"Book Collection successfully created.", "success")
            app.logger.info(f"{current_user.username} has successfully loaded the Book Collection to the Book Repository (admin_dashboard.html). Endpoint: load_books.")
        except BaseException:
            flash(f"Book Collection NOT created.", "danger")
            app.logger.warning(f"{current_user.username} has NOT loaded the Book Collection to the Book Repository (admin_dashboard.html). Endpoint: load_books.")
        finally:
            return redirect(url_for("admin_dashboard") or url_for("home_page"))
    else:
        flash(f"Sample Book Collection already created.", "info")
        return redirect(url_for("admin_dashboard"))


# --- // Error Handlers for 404 page not found, and 500 internal error.
@app.errorhandler(404)
def not_found(error):
    excuse = "Apologies, we can't seem to find the Book Repository database or worse, we've lost access to the Internet. Please click on the pink pulsating buoy to go to the Home Page (registering or signing in) or Member's Page (signed in), or click on Sign Out below."
    return render_template("oops.html", error=error, excuse=excuse, error_type="Client: 404 - Bad Request")


@app.errorhandler(500)
def internal_error(error):
    excuse = "Apologies, something serious occurred and the Leprechauns are working on resolving the issue. It's most likely Google Mail (GMail) acting up...again. Please click on the pink pulsating buoy to go to the Home Page (registering or signing in) or Member's Page (signed in), or click on Sign Out below."
    return render_template("oops.html", error=error, excuse=excuse, error_type="Server: 500 - Internal Server Error")


# export PRODUCTION=ON | OFF in TEST
# PRODUCTION App -> Settings -> Reveal Config Vars -> KEY: PRODUCTION,
# VALUE: ON
if __name__ == "__main__":
    if not os.environ.get("MONGO_URI_BR"):
        raise ValueError(
            "MongoDB Uniform Resource Identifier is missing, which means that we can't access the database.")
    elif not os.environ.get("ADMIN_PASSWORD"):
        raise ValueError(
            "Admin Password is not set which means that the Admin user can not be created.")
    elif not os.environ.get("MAIL_SERVER"):
        raise ValueError(
            "Mail Server Configuration error: MAIL_SERVER is not defined.")
    elif not os.environ.get("MAIL_PORT"):
        raise ValueError(
            "Mail Server Configuration error: MAIL_PORT is not defined.")
    elif not os.environ.get("MAIL_USERNAME"):
        raise ValueError(
            "Mail Server Configuration error: MAIL_USERNAME is not defined.")
    elif not os.environ.get("MAIL_PASSWORD"):
        raise ValueError(
            "Mail Server Configuration error: MAIL_PASSWORD is not defined.")
    elif not os.environ.get("USER_EMAIL_SENDER_EMAIL"):
        raise ValueError(
            "Mail Server Configuration error: USER_EMAIL_SENDER_EMAIL is not defined.")
    elif os.environ.get("PRODUCTION") == "ON":
        app.run(host=os.environ.get("IP"),
                port=os.environ.get("PORT"), debug=False)
    else:
        app.run(host=os.environ.get("IP"),
                port=os.environ.get("PORT"), debug=True)
