from django.contrib import messages
from django.contrib.auth import logout, authenticate, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from autodash_App import models, forms


def customer_sign_up(request):
    form = forms.CustomUserForm()
    if request.method == "POST":
        form = forms.CustomUserForm(request.POST)
        if form.is_valid():
            form.save()
            print("nope")
    context = {'form': form}
    return render(request, "auth/register.html", context=context)


def worker_sign_up(request):
    form = forms.CustomUserForm()
    if request.method == "POST":
        form = forms.CustomUserForm(request.POST)
        if form.is_valid():
            worker = form.save(commit=False)
            worker.role = "worker"
            worker.username = form.cleaned_data['phone_number']
            messages.success(request, "Worker registered successfully")
            worker.save()
            login(request, worker)
            return redirect('worker_confirm_branch')
        else:
            print(form.errors)
            messages.error(request, form.errors)
            print("nope")
            return redirect('worker_register')
    context = {'form': form}
    return render(request, "auth/register.html", context=context)


def login_page(request):
    if request.user.is_authenticated:
        messages.warning(request, "You are already logged in")
        return redirect('home')
    else:
        if request.method == 'POST':
            name = request.POST.get('phone_number')
            password = request.POST.get('pass')

            print(name)
            print(password)

            user = authenticate(request, username=name, password=password)
            print(user)
            if user:
                if not user.approved:
                    messages.warning(request, "You are not yet approved")
                    return redirect('login')
                login(request, user)
                messages.success(request, 'Log in Successful')
                return redirect('index')
            else:
                print("here")
                messages.info(request, 'Invalid username or password')
                return redirect('login')
    return render(request, "auth/login.html")


@login_required(login_url='login')
def logout_page(request):
    logout(request)
    messages.success(request, "Log out successful")
    return redirect('login')


@login_required(login_url='login')
def confirm_branch_of_work(request):
    user = models.CustomUser.objects.get(id=request.user.id)
    form = forms.ConfirmBranchForm
    if request.method == "POST":
        form = forms.ConfirmBranchForm(request.POST)
        if form.is_valid():
            branch = form.cleaned_data["branches"]
            print(branch)
            try:
                worker_account = models.Worker.objects.create(user=user, branch=branch)
                worker_account.save()
                messages.success(request, "Branch of work has been confirmed")
                return redirect('index')
            except Exception as e:
                print(e)
                messages.success(request, "Branch of work has been confirmed")
                return redirect('index')
    context = {'form': form}
    return render(request, "layouts/confirm_branch.html", context=context)


