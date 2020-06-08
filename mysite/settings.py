"""
Django settings for mysite project.

Generated by 'django-admin startproject' using Django 2.1.3.

For more information on this file, see
https://docs.djangoproject.com/en/2.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.1/ref/settings/
"""

import os

# Is the instance of the database being run on a local development computer or on the cluster
# options are 'local' or 'cluster'
DB_INSTANCE = 'local'

# path to file containing database password
PASSWORD_FILE = '/Users/erik/database_testing/password.txt'


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = '-#^pc5%n_!*d0s_t1xq83vzx%706#u+0y$itz*ltbc(((yzu*1'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', '10.59.210.245', '10.59.210.247', '10.59.210.197']


# django debug toolbar
# See https://django-debug-toolbar.readthedocs.io/en/latest/index.html
DEBUG_TOOLBAR = True      # Set this to True to show debug toolbar

if DEBUG_TOOLBAR == True:
    INTERNAL_IPS = ['127.0.0.1',]


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'debug_toolbar',
    'acmg_db',
    'crispy_forms',
    'auditlog',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'debug_toolbar.middleware.DebugToolbarMiddleware',
    'auditlog.middleware.AuditlogMiddleware'
]

ROOT_URLCONF = 'mysite.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'mysite.wsgi.application'


# Database
# https://docs.djangoproject.com/en/2.1/ref/settings/#databases

with open(PASSWORD_FILE) as f:
    password = f.readline().strip()


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'variant_classification_db',
	'USER': 'variant_classification_db_user',
	'PASSWORD': password,
	'HOST': 'localhost',
	'PORT': '',
    }
}


# Password validation
# https://docs.djangoproject.com/en/2.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    { 'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    { 'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    { 'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    { 'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]


# Internationalization
# https://docs.djangoproject.com/en/2.1/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Europe/London'
USE_I18N = True
USE_L10N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.1/howto/static-files/

STATIC_URL = '/static/'

# different static file settings for cluster and local
if DB_INSTANCE == 'cluster':
    STATIC_ROOT = os.path.join(BASE_DIR, 'static')
elif DB_INSTANCE == 'local':
    STATICFILES_DIRS = (os.path.join(BASE_DIR, 'static'),)
    ADMIN_MEDIA_PREFIX = '/static/admin/'

CRISPY_TEMPLATE_PACK = 'bootstrap4'



ENV_PATH = os.path.abspath(os.path.dirname(__file__))
MEDIA_ROOT = os.path.join(ENV_PATH, 'media/')
MEDIA_URL = '/media/'

LOGIN_REDIRECT_URL = 'home'
LOGIN_URL = '/login/'


# Enternal resources 

# Url to the Mutalyzer wsdl api
MUTALYZER_URL = 'https://mutalyzer.nl/services/?wsdl'
# Which Mutalyzer build to use
MUTALYZER_BUILD = 'hg19' 
# Which Reference genome for VEP to use
REFERENCE_GENOME = '/data/db/human/mappers/b37/bwa/human_g1k_v37.fasta'
# the value that will be added to the database to record VEP version
VEP_VERSION = '100'
# Which VEP Cache to use
VEP_CACHE = '/export/home/webapps/vep_100_cache/'
# Which temp directory to use for storing vcfs
VEP_TEMP_DIR = 'temp/'


