import logging

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import generic

from .models import Choice, Course, Enrollment, Submission

logger = logging.getLogger(__name__)


def registration_request(request):
    context = {}
    if request.method == "GET":
        return render(request, "onlinecourse/user_registration_bootstrap.html", context)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("psw", "")
        first_name = request.POST.get("firstname", "").strip()
        last_name = request.POST.get("lastname", "").strip()

        if not username or not password:
            context["message"] = "Username and password are required."
            return render(request, "onlinecourse/user_registration_bootstrap.html", context)

        if User.objects.filter(username=username).exists():
            context["message"] = "User already exists."
            return render(request, "onlinecourse/user_registration_bootstrap.html", context)

        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        login(request, user)
        return redirect("onlinecourse:index")

    return render(request, "onlinecourse/user_registration_bootstrap.html", context)


def login_request(request):
    context = {}
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("psw", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("onlinecourse:index")

        context["message"] = "Invalid username or password."
        return render(request, "onlinecourse/user_login_bootstrap.html", context)

    return render(request, "onlinecourse/user_login_bootstrap.html", context)


def logout_request(request):
    logout(request)
    return redirect("onlinecourse:index")


def check_if_enrolled(user, course):
    return user.is_authenticated and Enrollment.objects.filter(
        user=user, course=course
    ).exists()


class CourseListView(generic.ListView):
    template_name = "onlinecourse/course_list_bootstrap.html"
    context_object_name = "course_list"

    def get_queryset(self):
        courses = Course.objects.order_by("-total_enrollment")[:10]
        for course in courses:
            course.is_enrolled = check_if_enrolled(self.request.user, course)
        return courses


class CourseDetailView(generic.DetailView):
    model = Course
    template_name = "onlinecourse/course_details_bootstrap.html"
    context_object_name = "course"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.object
        context["is_enrolled"] = check_if_enrolled(self.request.user, course)
        context["questions"] = course.question_set.prefetch_related("choice_set")
        context["lessons"] = course.lesson_set.all()
        return context


def enroll(request, course_id):
    if not request.user.is_authenticated:
        return redirect("onlinecourse:login")

    course = get_object_or_404(Course, pk=course_id)
    Enrollment.objects.get_or_create(
        user=request.user, course=course, defaults={"mode": Enrollment.HONOR}
    )
    course.total_enrollment = Enrollment.objects.filter(course=course).count()
    course.save(update_fields=["total_enrollment"])
    return HttpResponseRedirect(
        reverse("onlinecourse:course_details", args=(course.id,))
    )


def extract_answers(request):
    """Collect valid integer choice IDs submitted by the exam form."""
    submitted_answers = []
    for key, value in request.POST.items():
        if key.startswith("choice"):
            try:
                submitted_answers.append(int(value))
            except (TypeError, ValueError):
                logger.warning("Ignoring invalid exam answer: %s", value)
    return submitted_answers


@login_required
def submit(request, course_id):
    if request.method != "POST":
        return redirect("onlinecourse:course_details", pk=course_id)

    course = get_object_or_404(Course, pk=course_id)
    enrollment, _ = Enrollment.objects.get_or_create(
        user=request.user, course=course, defaults={"mode": Enrollment.HONOR}
    )

    submission = Submission.objects.create(enrollment=enrollment)
    selected_ids = extract_answers(request)
    valid_choices = Choice.objects.filter(
        question__course=course, id__in=selected_ids
    )
    submission.choices.set(valid_choices)

    return redirect(
        "onlinecourse:show_exam_result",
        course_id=course.id,
        submission_id=submission.id,
    )


@login_required
def show_exam_result(request, course_id, submission_id):
    course = get_object_or_404(Course, pk=course_id)
    submission = get_object_or_404(
        Submission,
        pk=submission_id,
        enrollment__course=course,
        enrollment__user=request.user,
    )
    selected_ids = list(submission.choices.values_list("id", flat=True))
    questions = course.question_set.prefetch_related("choice_set")

    possible = 0
    total_score = 0
    results = []
    for question in questions:
        is_correct = question.is_get_score(selected_ids)
        earned = question.grade if is_correct else 0
        possible += question.grade
        total_score += earned
        results.append(
            {
                "question": question,
                "choices": question.choice_set.all(),
                "earned": earned,
                "is_correct": is_correct,
            }
        )

    grade = round((total_score / possible) * 100) if possible else 0
    context = {
        "course": course,
        "submission": submission,
        "submitted_choices": submission.choices.all(),
        "selected_ids": selected_ids,
        "questions": questions,
        "results": results,
        "total_score": total_score,
        "possible": possible,
        "possible_score": possible,
        "grade": grade,
        "passed": grade > 80,
    }
    return render(request, "onlinecourse/exam_result_bootstrap.html", context)
