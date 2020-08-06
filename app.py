import os
from flask import Flask, render_template_string, render_template, redirect, url_for, request, flash
from flask_mongoengine import MongoEngine, MongoEngineSession, MongoEngineSessionInterface
from flask_user import login_required, UserManager, UserMixin, current_user, roles_required
# from wtforms.validators import DataRequired
# from mongoengine.errors import NotUniqueError
import datetime
from flask_debugtoolbar import DebugToolbarExtension

# generates WTForms from MongoEngine models
# from flask_mongoengine.wtf import model_form


from config import ConfigClass

from dotenv import load_dotenv
from pathlib import Path
env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path)


""" Flask application factory """

# Setup Flask and load app.config
app = Flask(__name__, static_folder="static")
app.config.from_object(__name__+".ConfigClass")
app.debug = True

# Setup Flask-MongoEngine
db = MongoEngine(app)

# Use Flask Sessions with Mongoengine
app.session_interface = MongoEngineSessionInterface(db)

# Initiate the Flask Debug Toolbar Extension
toolbar = DebugToolbarExtension(app)

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

    # Relationships
    roles = db.ListField(db.StringField(), default=["user"])

    meta = {
        "auto_create_index": True,
        "index_background": True,
        "indexes": ["username"]
    }


class Book(db.Document):
    title = db.StringField(default="", maxlength=250)
    author = db.StringField(default="", maxlength=250)
    year = db.IntField(default="", maxlength=4)
    ISBN = db.IntField(default="", maxlength=13)
    short_description = db.StringField(default="A short description goes here. Please update this description. You have a maximum of 1500 characters to use.", maxlength=2000)
    user = db.StringField(required=True)
    creation_date = db.DateTimeField(default=datetime.datetime.now)
    comments = db.StringField(default="Please add your comments here. You have a maximum of 3000 characters to use, about the size of an A4 page.", maxlength=3500)
    rating = db.IntField(choices=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    private_view = db.StringField(default="")


    # def calc_votes(self):
        # self.rating = mean(n for n in self.votes if n is not None)

    meta = {
        "auto_create_index": True,
        "index_background": True,
        "indexes": ["title"],
        "ordering": ["-title"]
    }


# Setup Flask-User and specify the User data-model
user_manager = UserManager(app, db, User)


# Create admin user as first/default user, if admin does not exist. Password must be changed immediately upon first login.
if not User.objects.filter(User.username == "admin").first():
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


# The Home page is accessible to anyone


@app.route("/")
def home_page():
    if current_user.is_authenticated:
        return redirect(url_for("member_page"))
    return render_template("index.html")


# The Members page is only accessible to authenticated users via the @login_required decorator


@app.route("/members")
@login_required    # User must be authenticated
def member_page():
    # total_num_users = User.objects.count()
    # total_num_books = Book.objects.count()
    # print("\nTotal Number of Users:", total_num_users)
    # print("\nTotal Number of Books:", total_num_books)

    filtered_books = Book.objects.filter(user=current_user.username)
    # filtered_books_as_json = filtered_books.to_json()
    # print("Filtered Books as JSON:", filtered_books_as_json)

    """ book = Book(
        title="Fresh Spice",
        author="Arun Kapil",
        year=2014,
        ISBN=9781909108479,
        user=current_user.username,
        short_description="Vibrant recipes for bringing flavour, depth, and colour to home cooking.",
        comments="I love reading this book, dreaming of the recipes I can make. I made the Lamb Vindaloo and it was gorgeous. Good Samosas are hard to make.",
        rating=8,
        private_view = ""
    ).save()
    
    book = Book(
        title="The Art of War",
        author="Sun Tzu",
        year=1991,
        ISBN=9780877735373,
        user=current_user.username,
        short_description="Thomas Cleary's translation and commentary of the 2000 year old piece on the Art of War.",
        comments="Nothing like a little management bullshit.",
        rating=4,
        private_view = ""
    ).save()
    
    book = Book(
        title="Festa",
        author="Eileen Dunne Crescenzi",
        year=2015,
        ISBN=9780717164448,
        user=current_user.username,
        short_description="Recipes and recollections.",
        comments="An veritable feast of Italian dishes.",
        rating=7,
        private_view = ""
    ).save() """

    user_books = Book.objects.filter(user=current_user.username)
    return render_template("members.html", user_books=user_books)


@app.route("/edit_book/<book_id>")
@login_required
def edit_book(book_id):
    book = Book.objects.get(id=book_id)
    return render_template("edit_book.html", book=book)


@app.route("/update_book/<book_id>", methods=["POST"])
@login_required
def update_book(book_id):
    book = Book.objects.get(id=book_id)
    fields = {
        "title": request.form.get("title"),
        "author": request.form.get("author"),
        "year": request.form.get("year"),
        "ISBN": request.form.get("isbn"),
        "short_description": request.form.get("short_description"),
        "comments": request.form.get("comments"),
        "rating": request.form.get("rating"),
        "private_view": request.form.get("private_view")
    }
    try:
        book.update(**fields)
        flash(f"The book '{book.title}' is updated successfully by '{current_user.username}'.", "success")
    except:
        flash(f"The book '{book.title}' did NOT update successfully by '{current_user.username}'.", "danger")
    return redirect(url_for("member_page"))


@app.route("/delete_book/<book_id>")
@login_required
def delete_book(book_id):
    book = Book.objects.get(id=book_id)
    try:
        book.delete()
        flash(f"The book '{book.title}' is deleted successfully by '{current_user.username}'.", "success")
    except:
        flash(f"The book '{book.title}' was NOT deleted successfully by '{current_user.username}'.", "danger")
    return redirect(url_for("member_page"))


# export PRODUCTION=ON | OFF in TEST
# PRODUCTION App -> Settings -> Reveal Config Vars -> KEY: PRODUCTION, VALUE: ON
if __name__ == "__main__":
    if os.environ.get("PRODUCTION") == "ON":
        app.run(host=os.environ.get("IP"),
                port=os.environ.get("PORT"), debug=False)
    else:
        app.run(host=os.environ.get("IP"),
                port=os.environ.get("PORT"), debug=True)
