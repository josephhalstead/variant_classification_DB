from django.shortcuts import render, get_object_or_404, redirect
from .forms import *
from django.conf import settings
from .models import *
from .utils.variant_utils import *
from django.utils import timezone
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.core.exceptions import PermissionDenied
import json
import base64
from django.core.files.base import ContentFile
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import UserCreationForm
from io import TextIOWrapper
from django.db import transaction

@transaction.atomic
@login_required
def auto_input(request):
	"""
	Allows users to upload a file of variants to classify.

	"""

	# make a list of all panels and pass to the form to populate the dropdown
	panel_options = [(str(panel.pk), panel.panel) for panel in Panel.objects.all()]

	# Inititate the upload form
	form = VariantFileUploadForm(options=panel_options)

	# make empty dict for context
	context = {
		'form': form, 
		'error': None,
		'warn': None,
		'success': None,
		'params': None
	}

	if request.POST:

		form = VariantFileUploadForm(request.POST, request.FILES, options=panel_options)

		if form.is_valid():

			# get panel
			analysis_performed_pk = form.cleaned_data['panel_applied']
			panel_obj = get_object_or_404(Panel, panel = analysis_performed_pk)

			# get affected with
			affected_with = form.cleaned_data['affected_with']

			# process tsv file
			raw_file = request.FILES['variant_file']
			utf_file = TextIOWrapper(raw_file, encoding='utf-8')
			df, meta_dict = load_worksheet(utf_file)

			# Get key information from the dataframe
			# We have checked that there is only one sample/worksheet in the df 
			unique_variants =  df['Variant'].unique()
			worksheet_id = df['WorklistId'].unique()[0]
			sample_id = df['#SampleId'].unique()[0]

			# add worksheet
			worksheet_obj, created = Worklist.objects.get_or_create(
					name = worksheet_id
					)

			# add sample
			try:
				sample_obj = Sample.objects.get(name=worksheet_id + '-' + sample_id)

				# throw error if the sample has been uploaded before with the same panel (wont throw error if its a different panel)
				if sample_obj.analysis_performed.panel == analysis_performed_pk:
					context['error'] = [f'ERROR: {sample_obj.name} has already been uploaded with the {analysis_performed_pk} panel.']
					return render(request, 'acmg_db/auto_input.html', context)

			except Sample.DoesNotExist:
				sample_obj = Sample.objects.create(
						name = worksheet_id + '-' + sample_id,
						sample_name_only = sample_id,
						worklist = worksheet_obj,
						affected_with = affected_with,
						analysis_performed = panel_obj,
						analysis_complete = False,
						other_changes = ''
						)
				sample_obj.save()

			# Get VEP annotations
			vep_info_dict = {
				'reference_genome' : settings.REFERENCE_GENOME,
				'vep_cache': settings.VEP_CACHE,
				'temp_dir': settings.VEP_TEMP_DIR
			}

			variant_annotations = get_vep_info_local(unique_variants, vep_info_dict, sample_id)

			# Loop through each variant and add to the database
			for variant in variant_annotations:

				var = variant[1]
				variant_data = process_variant_input(var)

				key = variant_data[5]
				variant_hash = variant_data[0]
				chromosome = variant_data[1]
				position = variant_data[2]
				ref = variant_data[3]
				alt = variant_data[4]
					
				variant_obj, created = Variant.objects.get_or_create(
						key = key,
						variant_hash = variant_hash,
						chromosome = chromosome,
						position = position,
						ref = ref,
						alt = alt
						)

				if 'transcript_consequences' in variant[0]:

					consequences = variant[0]['transcript_consequences']

				elif 'intergenic_consequences' in variant[0]:

					consequences = variant[0]['intergenic_consequences']

				else:

					raise Exception(f'Could not get the consequences for variant {variant}')

				selected = None

				# Loop through each consequence/transcript
				for consequence in consequences:

					if 'transcript_id' in consequence:

						transcript_id = consequence['transcript_id']

					else:

						transcript_id = 'None'

					transcript_hgvsc = consequence.get('hgvsc')
					transcript_hgvsp = consequence.get('hgvsp')
					gene_symbol = consequence.get('gene_symbol', 'None')
					exon = consequence.get('exon', 'NA')
					impact = consequence.get('consequence_terms')
					impact = '|'.join(impact)


					gene_obj, created = Gene.objects.get_or_create(
						name = gene_symbol
						)

					transcript_obj, created = Transcript.objects.get_or_create(
							name = transcript_id,
							gene = gene_obj
						)

					transcript_variant_obj, created = TranscriptVariant.objects.get_or_create(
						variant = variant_obj,
						transcript = transcript_obj,
						hgvs_c = transcript_hgvsc,
						hgvs_p = transcript_hgvsp,
						exon = exon,
						consequence = impact

						)
					# Find the transcript that VEP has picked
					if 'pick' in consequence:

						selected = transcript_variant_obj

				new_classification_obj = Classification.objects.create(
					variant= variant_obj,
					sample = sample_obj,
					creation_date = timezone.now(),
					user_creator = request.user,
					status = '0',
					is_trio_de_novo = False,
					first_final_class = '7',
					second_final_class = '7',
					selected_transcript_variant = selected
					)

				new_classification_obj.save()

			success = ['Worksheet {} - Sample {} - Upload completed '.format(worksheet_id, sample_id)]
			params = '?worksheet={}&sample={}'.format(worksheet_id, sample_id)

			context = {
					'form': form, 
					'success': success,
					'params': params
					}


	return render(request, 'acmg_db/auto_input.html', context)


#--------------------------------------------------------------------------------------------------
@transaction.atomic
@login_required
def manual_input(request):
	"""
	The view for the manual input page.

	Allows users to create a new classification for a variant.
	"""


	# make a list of all panels and pass to the form to populate the dropdown
	panel_options = [(str(panel.pk), panel.panel) for panel in Panel.objects.all()]

	form = ManualUploadForm(options =panel_options )
	context = {
		'form': form,
		'error': [], 
	}

	# If the user has clicked submit
	if request.POST:

		form = ManualUploadForm(request.POST, options =panel_options)

		if form.is_valid():

			cleaned_data = form.cleaned_data
			
			# Get the user input from the form.
			search_query = cleaned_data['variant'].strip()
			gene_query = cleaned_data['gene'].strip()
			transcript_query = cleaned_data['transcript'].strip()
			hgvs_c_query = cleaned_data['hgvs_c'].strip()
			hgvs_p_query = cleaned_data['hgvs_p'].strip()
			exon_query = cleaned_data['exon'].strip()

			sample_name_query = cleaned_data['sample_name'].strip()
			affected_with_query = cleaned_data['affected_with'].strip()
			analysis_performed_query = cleaned_data['analysis_performed'].strip()
			other_changes_query = cleaned_data['other_changes'].strip()
			worklist_query = cleaned_data['worklist'].strip()
			consequence_query = cleaned_data['consequence'].strip()
		
			# Validate the variant using Mutalyzer - i.e. is the variant real?
			# We only check if the chr-pos-ref-alt is real not if gene etc is correct.
			variant_info = get_variant_info_mutalzer(search_query, settings.MUTALYZER_URL, settings.MUTALYZER_BUILD)

			if variant_info[0] == True:

				# Add variant to DB if not already present
				# Get variant information e.g. chr, pos, ref, alt from the input

				variant_data = process_variant_input(search_query)

				variant_hash = variant_data[0]
				chromosome = variant_data[1]
				position = variant_data[2]
				ref = variant_data[3]
				alt = variant_data[4]
				key = variant_data[5]

				# Create the objects
				worklist, created = Worklist.objects.get_or_create(
					name = worklist_query

				)

				panel = get_object_or_404(Panel, panel=analysis_performed_query)

				# Get or create working strangely on samples so create it the old fashioned way.
				try:

					sample_obj = Sample.objects.get(name=worklist_query + '-' + sample_name_query)

				except Sample.DoesNotExist:

					sample_obj = Sample.objects.create(
						name = worklist_query + '-' + sample_name_query,
						sample_name_only = sample_name_query,
						worklist = worklist,
						affected_with = affected_with_query,
						analysis_performed = panel,
						analysis_complete = False,
						other_changes = other_changes_query
							)

					sample_obj.save()

				variant, created = Variant.objects.get_or_create(
					key = key,
					variant_hash = variant_hash,
					chromosome = chromosome,
					position = position,
					ref = ref,
					alt = alt
				)

				gene, created = Gene.objects.get_or_create(
					name = gene_query
				)

				transcript, created = Transcript.objects.get_or_create(
					name = transcript_query,
					gene = gene
				)			

				transcript_variant, created = TranscriptVariant.objects.get_or_create(
					variant = variant,
					transcript = transcript,
					hgvs_c = hgvs_c_query,
					hgvs_p = hgvs_p_query,
					exon = exon_query,
					consequence = consequence_query
				)

				new_classification_obj = Classification.objects.create(
					variant= variant,
					sample = sample_obj,
					creation_date = timezone.now(),
					user_creator = request.user,
					status = '0',
					is_trio_de_novo = False,
					first_final_class = '7',
					second_final_class = '7',
					selected_transcript_variant = transcript_variant
				)

				new_classification_obj.save()
				
				# Go to the new_classification page.
				return redirect(new_classification, new_classification_obj.pk)

			else:

				context['error'] = variant_info[1][0]

				return render(request, 'acmg_db/manual_input.html', context)


	return render(request, 'acmg_db/manual_input.html', context)


#--------------------------------------------------------------------------------------------------
@transaction.atomic
@login_required
def new_classification(request, pk):
	"""
	Page for entering new classifications.

	Has the following featues:

	1) Forms for entering variant and sample information
	2) Form for selecting whether the variant is genuine
	3) ACMG classifier.
	4) Comments and Evidence.
	5) Final submit form

	"""

	classification = get_object_or_404(Classification, pk=pk)

	# Assign first check to first person to click the link
	if classification.user_first_checker == None:

		classification.user_first_checker = request.user
		classification.save()

	#reject if wrong status or user
	if classification.status != '0' or request.user != classification.user_first_checker:

		raise PermissionDenied('You do not have permission to start this classification.')

	else:

		# Get data to render form
		variant = classification.variant
		previous_classifications = Classification.objects.filter(variant=variant, status__in=['2', '3']).exclude(pk=classification.pk).order_by('-second_check_date')
		previous_full_classifications = previous_classifications.filter(genuine='1').order_by('-second_check_date')
		answers = ClassificationAnswer.objects.filter(classification=classification).order_by('classification_question__order')
		comments = UserComment.objects.filter(classification=classification, visible=True)
		result = classification.display_first_classification()  # current class to display
		transcript = classification.selected_transcript_variant.transcript
		refseq_options = TranscriptVariant.objects.filter(variant=variant)
		fixed_refseq_options = []

		# Get relevant options for the variant transcripts
		for transcript_var in refseq_options:

			fixed_refseq_options.append((transcript_var.pk, transcript_var.transcript.name + ' - ' + transcript_var.transcript.gene.name + ' - ' + transcript_var.consequence))

		# make a list of all panels and pass to the form to populate the dropdown
		panel_options = [(str(panel.pk), panel.panel) for panel in Panel.objects.all()]

		# make empty instances of forms
		sample_form = SampleInfoForm(classification_pk=classification.pk, options=panel_options)
		variant_form = VariantInfoForm(classification_pk=classification.pk, options=fixed_refseq_options)
		genuine_form = GenuineArtefactForm(classification_pk=classification.pk)
		finalise_form = FinaliseClassificationForm(classification_pk=classification.pk)

		# dict of data to pass to view
		context = {
			'classification': classification,
			'variant': variant,
			'previous_classifications': previous_classifications,
			'previous_full_classifications': previous_full_classifications,
			'answers': answers,
			'comments': comments,
			'result': result,
			'sample_form': sample_form,
			'variant_form': variant_form,
			'genuine_form': genuine_form,
			'finalise_form': finalise_form,
			'warn': []
		}
		
		#-----------------------------------------------
		# if a form is submitted
		if request.method == 'POST':

			# SampleInfoForm
			if 'affected_with' in request.POST:

				sample_form = SampleInfoForm(request.POST, classification_pk=classification.pk, options = panel_options)

				# load in data
				if sample_form.is_valid():

					cleaned_data = sample_form.cleaned_data


					panel = get_object_or_404(Panel, panel = cleaned_data['analysis_performed'])

					sample = classification.sample
					sample.analysis_performed = panel
					sample.affected_with =  cleaned_data['affected_with']
					sample.other_changes = cleaned_data['other_changes']
					sample.save()
					
				# reload dict variables for rendering
				context['classification'] = get_object_or_404(Classification, pk=pk)
				context['sample_form'] = SampleInfoForm(classification_pk=classification.pk, options=panel_options)

			# VariantInfoForm
			if 'inheritance_pattern' in request.POST:

				variant_form = VariantInfoForm(request.POST, classification_pk = classification.pk, options=fixed_refseq_options)

				if variant_form.is_valid():

					cleaned_data = variant_form.cleaned_data

					# transcript section
					select_transcript = cleaned_data['select_transcript']
					selected_transcript_variant = get_object_or_404(TranscriptVariant, pk=select_transcript)
					classification.selected_transcript_variant = selected_transcript_variant
					classification.is_trio_de_novo = cleaned_data['is_trio_de_novo']
					classification.save()

					# genes section
					gene = classification.selected_transcript_variant.transcript.gene
					gene.inheritance_pattern = cleaned_data['inheritance_pattern']
					gene.conditions = cleaned_data['conditions']
					gene.save()

				# reload dict variables for rendering
				context['classification'] = classification
				context['variant_form'] = VariantInfoForm(classification_pk=classification.pk, options=fixed_refseq_options)

			# GenuineArtefactForm
			if 'genuine' in request.POST:

				genuine_form = GenuineArtefactForm(request.POST, classification_pk=classification.pk)

				if genuine_form.is_valid():
					cleaned_data = genuine_form.cleaned_data

					# genuine - new classification
					if cleaned_data['genuine'] == '1':

						classification.genuine = '1'

						# if not already initiated, make new classification answers
						if len(answers) == 0:
							classification.initiate_classification()

						# save final_class as output of calculate_acmg_score_first
						classification.first_final_class = classification.calculate_acmg_score_first()[1]

					# genuine - use previous classification
					elif cleaned_data['genuine'] == '2':

						# if there isnt a previous classification, throw a warning and stop
						if len(previous_classifications) == 0:

							context['warn'] += ['There are no previous classifications to use.']

						# if there is, update final class to whatever it was previously
						else:

							classification.genuine = '2'
							classification.first_final_class = previous_full_classifications[0].second_final_class

					# genuine - not analysed - update final_class to 'not analysed'
					elif cleaned_data['genuine'] == '3':

						classification.genuine = '3'
						classification.first_final_class = '7'

					# artefact - set final_class to artefact
					elif cleaned_data['genuine'] == '4':

						classification.genuine = '4'
						classification.first_final_class = '6'
						
					classification.save()

				# reload dict variables for rendering
				result = classification.display_first_classification()
				context['result'] = result
				context['answers'] = ClassificationAnswer.objects.filter(classification=classification)
				context['classification'] = get_object_or_404(Classification, pk=pk)
				context['genuine_form'] = GenuineArtefactForm(classification_pk=classification.pk)


			# FinaliseClassificationForm
			if 'final_classification' in request.POST:

				# Don't let anyone except the assigned first checker submit the form
				if classification.status != '0' or request.user != classification.user_first_checker:

					raise PermissionDenied('You do not have permission to finalise the classification.')

				finalise_form = FinaliseClassificationForm(request.POST, classification_pk=classification.pk)

				if finalise_form.is_valid():

					cleaned_data = finalise_form.cleaned_data

					# validation that everything has been completed - make sure all fields are completed, genuine/artefact is set
					if classification.genuine == '0':

						context['warn'] += ['Select whether the variant is genuine or artefact']

					if classification.selected_transcript_variant.transcript.gene.inheritance_pattern == None or classification.selected_transcript_variant.transcript.gene.inheritance_pattern == '':

						context['warn'] += ['Inheritence pattern has not been set']

					if classification.selected_transcript_variant.transcript.gene.conditions == None or classification.selected_transcript_variant.transcript.gene.conditions == '':

						context['warn'] += ['Gene associated conditions have not been set']

					if classification.genuine  == '2' and (cleaned_data['final_classification'] != previous_full_classifications[0].second_final_class):

						context['warn'] += ['You selected to use the last full classification, but the selected classification does not match']

					if classification.genuine  == '3' and (cleaned_data['final_classification'] != '7' ):

						context['warn'] += ['This classification was selected as Not Analysed - therefore the only valid option is NA']

					if classification.genuine  == '4' and (cleaned_data['final_classification'] != '6' ):

						context['warn'] += ['This classification was selected as Artefect - therefore the only valid option is Artefect']

					# if validation has been passed, finalise first check
					if len(context['warn']) == 0:
						
						# if new classification, pull score from the acmg section and save to final class
						if classification.genuine == '1':

							classification.first_final_class = classification.calculate_acmg_score_first()[1]

						# if anything other than 'dont override' selected, then change the classification
						if cleaned_data['final_classification'] != '8':

							classification.first_final_class = cleaned_data['final_classification']

						# update status and save
						classification.status = '1'
						classification.first_check_date = timezone.now()
						classification.user_first_checker = request.user
						classification.save()

						#return redirect('home')
						return redirect('/view_previous_classifications?sample={}&worksheet={}&panel={}'.format(
							classification.sample.sample_name_only,
							classification.sample.worklist.name,
							classification.sample.analysis_performed.panel
						))

			return render(request, 'acmg_db/new_classifications.html', context)
		return render(request, 'acmg_db/new_classifications.html', context)


#--------------------------------------------------------------------------------------------------
@transaction.atomic
@login_required
def ajax_acmg_classification_first(request):
	"""
	Gets the ajax results from the new_classifications.html page \
	and stores them in the database - also returns the calculated result.

	This view is for the first check.

	"""

	if request.is_ajax():

		# Get the submitted answers and convert to python object
		classification_answers = request.POST.get('classifications')
		classification_answers = json.loads(classification_answers)

		# Get the classification pk and load the classification
		classification_pk = request.POST.get('classification_pk').strip()
		classification = get_object_or_404(Classification, pk =classification_pk)

		# Ensure correct user and status
		if classification.status != '0' or request.user != classification.user_first_checker:

			raise PermissionDenied('You do not have permission to start this classification.')

		correct_number_of_questions = ClassificationQuestion.objects.all().count()

		if len(classification_answers) != correct_number_of_questions:

			raise Exception('Wrong number of questions')

		# Update the classification answers
		for classification_answer in classification_answers:

			pk = classification_answer.strip()

			classification_answer_obj = get_object_or_404(ClassificationAnswer, pk=pk)

			classification_answer_obj.strength_first = classification_answers[classification_answer][1].strip()

			classification_answer_obj.selected_first = classification_answers[classification_answer][2].strip()

			classification_answer_obj.comment = classification_answers[classification_answer][3].strip()

			classification_answer_obj.save()

		# Calculate the score
		result = classification.calculate_acmg_score_first()[0]

		# update the score in the database
		classification.first_final_class = classification.calculate_acmg_score_first()[1]
		classification.save()

		html = render_to_string('acmg_db/acmg_results_first.html', {'result': classification.display_first_classification()})

	return HttpResponse(html)


#--------------------------------------------------------------------------------------------------
@transaction.atomic
@login_required
def ajax_acmg_classification_second(request):
	"""
	Gets the ajax results from the new_classifcations.html page \
	and stores them in the database - also returns the calculated result.

	This view is for the second check.
	"""

	if request.is_ajax():

		# Get the submitted answers and convert to python object
		classification_answers = request.POST.get('classifications')
		classification_answers = json.loads(classification_answers)

		# Get the classification pk and load the classification
		classification_pk = request.POST.get('classification_pk').strip()
		classification = get_object_or_404(Classification, pk =classification_pk)

		# Ensure correct user and status
		if classification.status != '1' or request.user != classification.user_second_checker:

			raise PermissionDenied('You do not have permission to start this classification.')

		# Check we have every question
		correct_number_of_questions = ClassificationQuestion.objects.all().count()

		if len(classification_answers) != correct_number_of_questions:

			raise Exception('Wrong number of questions')


		# Update the classification answers
		for classification_answer in classification_answers:

			pk = classification_answer.strip()

			classification_answer_obj = get_object_or_404(ClassificationAnswer, pk=pk)

			classification_answer_obj.strength_second= classification_answers[classification_answer][1].strip()

			classification_answer_obj.selected_second = classification_answers[classification_answer][2].strip()

			classification_answer_obj.comment = classification_answers[classification_answer][3].strip()

			classification_answer_obj.save()

		acmg_result_first = classification.display_first_classification()

		acmg_result_second = classification.calculate_acmg_score_second()[0].split('(')[0]

		if acmg_result_second == 'VUS - contradictory evidence provided':

			acmg_result_second = 'Contradictory evidence provided'

		html = render_to_string('acmg_db/acmg_results_second.html', {'result_first': acmg_result_first, 'result_second': acmg_result_second})

	return HttpResponse(html)


#--------------------------------------------------------------------------------------------------
@transaction.atomic
@login_required
def ajax_comments(request):
	"""
	Ajax View - when the user clicks the upload comment/file button \
	this updates the comment section of the page. 
	Clipboard paste only works on HTML5 enabled browser.
	"""

	if request.is_ajax():

		classification_pk = request.POST.get('classification_pk')
		comment_text = request.POST.get('comment_text')

		classification_pk = classification_pk.strip()
		comment_text = comment_text.strip()

		classification = get_object_or_404(Classification, pk =classification_pk)

		if len(comment_text) >1: #Check user has entered a comment

			new_comment = UserComment(user=request.user,
								text=comment_text,
								time=timezone.now(),
								classification=classification)

			new_comment.save()

			#Deal with files selected using the file selector html widget 
			if request.FILES.get('file', False) != False:

				file = request.FILES.get('file')

				new_evidence = Evidence()

				new_evidence.file = file

				new_evidence.comment= new_comment

				new_evidence.save()

			#Deal with images pasted in from the clipboard
			if request.POST.get('image_data') != None: 

				image_data = request.POST.get('image_data')

				#strip of any leading characters
				image_data = image_data.strip() 

				#add appropiate file header
				dataUrlPattern = re.compile('data:image/(png|jpeg);base64,(.*)$') 

				ImageData = dataUrlPattern.match(image_data).group(2)

				ImageData = base64.b64decode(ImageData) #to binary

				new_evidence = Evidence()

				new_evidence.comment= new_comment

				#save image
				img_file_string = '{}_{}_clip_image.png'.format(classification.pk,new_comment.pk)
				new_evidence.file.save(img_file_string, ContentFile(ImageData)) 

				new_evidence.save()

		comments = UserComment.objects.filter(classification=classification, visible=True)

		html = render_to_string('acmg_db/ajax_comments.html',
								{'comments': comments})

		return HttpResponse(html)

	else:

		raise Http404



#--------------------------------------------------------------------------------------------------
@transaction.atomic
@login_required
def view_previous_classifications(request):
	"""
	Page to view previous classifications

	"""

	classifications = Classification.objects.all().order_by('-creation_date')

	return render(request, 'acmg_db/view_classifications.html', {'classifications': classifications})


@transaction.atomic
@login_required
def view_classification(request, pk):
	"""
	View a read only version of a classification of a variant

	"""

	classification = get_object_or_404(Classification, pk=pk)

	# Allow users to archive the classification
	if request.method == 'POST':

		if 'submit-archive' in request.POST:

			if classification.status == '2':

				form = ArchiveClassificationForm(request.POST, classification_pk = classification.pk)

				if form.is_valid():

					# Update status to archived
					cleaned_data = form.cleaned_data
					classification.status = '3'
					classification.save()
					return redirect('home')

			else:

				raise PermissionDenied('You do not have permission to archive the classification.')

		# Allow users to reset a classification
		elif 'submit-reset' in request.POST:

			# Only allow user to reset if status is first or second analysis
			if classification.status == '0' or classification.status == '1':

				form = ResetClassificationForm(request.POST, classification_pk = classification.pk)

				if form.is_valid():

					classification = get_object_or_404(Classification, pk=form.classification_pk)

					classification.first_check_date = None
					classification.second_check_date = None
					classification.user_first_checker = None
					classification.user_second_checker = None
					classification.status = '0'
					classification.genuine = '0'
					classification.first_final_class = '7'
					classification.second_final_class = '7'
					classification.save()

					answers = ClassificationAnswer.objects.filter(classification=classification)
					answers.delete()

					return redirect('home')

			else:

				raise PermissionDenied('You do not have permission to reset the classification.')

		# Allow users to assign the second check to themselves
		elif 'submit-assign' in request.POST:

			# Only allow user to reset if status is first or second analysis
			if classification.status == '1' and classification.user_second_checker != request.user:

				form = AssignSecondCheckToMeForm(request.POST, classification_pk = classification.pk)

				if form.is_valid():

					classification = get_object_or_404(Classification, pk=form.classification_pk)

					classification.user_second_checker = request.user
					classification.save()

					return redirect('home')

			else:

				raise PermissionDenied('You do not have permission to assign the second check to yourself.')	


	else:

		# Otherwise just get the information for display
		classification_answers = (ClassificationAnswer.objects.filter(classification=classification)
			.order_by('classification_question__order'))

		comments = UserComment.objects.filter(classification=classification, visible=True)

		acmg_result = classification.calculate_acmg_score_second()

		archive_form = ArchiveClassificationForm(classification_pk = classification.pk)
		reset_form = ResetClassificationForm(classification_pk = classification.pk)
		assign_form = AssignSecondCheckToMeForm(classification_pk = classification.pk)

		return render(request, 'acmg_db/view_classification.html', {'classification': classification,
									 'classification_answers': classification_answers,
									 'comments': comments,
									 'acmg_result': acmg_result,
									 'archive_form': archive_form,
									 'reset_form': reset_form,
									 'assign_form': assign_form})


@login_required
@transaction.atomic
def second_check(request, pk):
	"""
	Page for entering doing a second check classifications.

	"""

	classification = get_object_or_404(Classification, pk=pk)

	# Assign second check to first person to click the link
	if classification.user_second_checker == None:

		classification.user_second_checker = request.user
		classification.save()

	#reject if wrong status or user
	if classification.status != '1' or request.user != classification.user_second_checker:

		raise PermissionDenied(f'You do not have permission to perform the second check. It is assigned to {request.user}')

	else:
		# Get data to render form
		variant = classification.variant

		previous_classifications = Classification.objects.filter(variant=variant, status__in=['2', '3']).exclude(pk=classification.pk).order_by('-second_check_date')
		previous_full_classifications = previous_classifications.filter(genuine='1').order_by('-second_check_date')

		answers = ClassificationAnswer.objects.filter(classification=classification).order_by('classification_question__order')
		comments = UserComment.objects.filter(classification=classification, visible=True)

		result_first = classification.display_first_classification()
		result_second = classification.calculate_acmg_score_second()[0].split('(')[0]  # current class to display

		if result_second == 'VUS - contradictory evidence provided':

			result_second = 'Contradictory evidence provided'

		transcript = classification.selected_transcript_variant.transcript

		panel_options = [(str(panel.pk), panel.panel) for panel in Panel.objects.all()]

		# make empty instances of forms
		sample_form = SampleInfoFormSecondCheck(classification_pk=classification.pk, options=panel_options)
		finalise_form = FinaliseClassificationSecondCheckForm(classification_pk=classification.pk)

		# dict of data to pass to view
		context = {
			'classification': classification,
			'variant': variant,
			'previous_classifications': previous_classifications,
			'previous_full_classifications': previous_full_classifications,
			'answers': answers,
			'comments': comments,
			'result_first': result_first,
			'result_second': result_second,
			'sample_form': sample_form,
			'finalise_form': finalise_form,
			'warn': []
		}
		
		#-----------------------------------------------
		# if a form is submitted
		if request.method == 'POST':

			# SampleInfoForm
			if 'affected_with' in request.POST:

				sample_form = SampleInfoFormSecondCheck(request.POST, classification_pk=classification.pk, options=panel_options)

				# load in data
				if sample_form.is_valid():

					cleaned_data = sample_form.cleaned_data

					panel = get_object_or_404(Panel, panel = cleaned_data['analysis_performed'])

					sample = classification.sample
					sample.analysis_performed = panel
					sample.affected_with =  cleaned_data['affected_with']
					sample.other_changes = cleaned_data['other_changes']
					sample.save()
					
				
				# reload dict variables for rendering
				context['classification'] = classification
				context['sample_form'] = SampleInfoFormSecondCheck(classification_pk=classification.pk, options=panel_options)

			# FinaliseClassificationForm
			if 'final_classification' in request.POST:

				# Don't let anyone except the assigned second checker submit the form
				if classification.status != '1' or request.user != classification.user_second_checker:

					raise PermissionDenied('You do not have permission to finalise the classification.')

				finalise_form = FinaliseClassificationSecondCheckForm(request.POST, classification_pk=classification.pk)

				if finalise_form.is_valid():

					cleaned_data = finalise_form.cleaned_data

					# validation that everything has been completed - make sure all fields are completed, genuine/artefact is set

					if classification.genuine == '0':

						context['warn'] += ['Select whether the variant is genuine or artefact']

					if classification.selected_transcript_variant.transcript.gene.inheritance_pattern == None or classification.selected_transcript_variant.transcript.gene.inheritance_pattern == '':

						context['warn'] += ['Inheritence pattern has not been set']

					if classification.selected_transcript_variant.transcript.gene.conditions == None or classification.selected_transcript_variant.transcript.gene.conditions == '':

						context['warn'] += ['Gene associated conditions have not been set']

					if classification.genuine  == '2' and (cleaned_data['final_classification'] != previous_full_classifications[0].second_final_class):

						context['warn'] += ['You selected to use the last full classification, but the selected classification does not match']

					if classification.genuine  == '3' and cleaned_data['final_classification'] != '7':

						context['warn'] += ['This classification was selected as Not Analysed - therefore the only option is NA']

					if classification.genuine  == '4' and cleaned_data['final_classification'] != '6' :

						context['warn'] += ['This classification was selected as Artefect - therefore the only valid option is Artefect']

					# if validation has been passed, finalise first check
					if len(context['warn']) == 0:

						# if new classification, pull score from the acmg section and save to final class
						if classification.genuine == '1':

							classification.second_final_class = classification.calculate_acmg_score_second()[1]

						# if anything other than 'dont override' selected, then change the classification
						if cleaned_data['final_classification'] != '8':

							classification.second_final_class = cleaned_data['final_classification']

						# update status and save
						classification.status = '2'
						classification.second_check_date = timezone.now()
						classification.user_second_checker = request.user
						classification.save()

						#return redirect('home')
						return redirect('/view_previous_classifications?sample={}&worksheet={}&panel={}'.format(
							classification.sample.sample_name_only,
							classification.sample.worklist.name,
							classification.sample.analysis_performed.panel
						))

			return render(request, 'acmg_db/second_check_new.html', context)
		return render(request, 'acmg_db/second_check_new.html', context)


@transaction.atomic
def signup(request):
	"""
	Allow users to sign up
	User accounts are inactive by default - an admin must activate it using the admin page.

	"""

	if request.method == 'POST':

		form = UserCreationForm(request.POST)

		if form.is_valid():

			form.save()
			username = form.cleaned_data.get('username')
			raw_password = form.cleaned_data.get('password1')
			user = authenticate(username=username, password=raw_password)
			user.is_active = False
			user.save()

			return redirect('home')

		else:

			form = UserCreationForm()
			return render(request, 'acmg_db/signup.html', {'form': form, 'warning' : ['Could not create an account.']})

	else:

		form = UserCreationForm()
		return render(request, 'acmg_db/signup.html', {'form': form, 'warning': []})


@transaction.atomic
@login_required
def about(request):
	"""
	The about page. Displays information about the application.
	"""

	return render(request, 'acmg_db/about.html', {})


@transaction.atomic
@login_required
def view_variants(request):
	"""
	Page to view all unique variants classified in the lab

	"""
	all_variants = Variant.objects.all().order_by('chromosome', 'position')

	# annotate each variant with information about how it was classified
	most_recent_classifications = [[variant, variant.most_recent_classification()] for variant in all_variants]

	# Filter out the variants with no classification
	most_recent_classifications = list(filter(lambda x: x[1][0] != None, most_recent_classifications))

	return render(request, 'acmg_db/view_variants.html', {'all_variants': most_recent_classifications})


@transaction.atomic
@login_required
def view_variant(request, pk):
	"""
	Page to view information about a specific variant.

	"""

	variant = get_object_or_404(Variant, variant_hash = pk)

	classifications = Classification.objects.filter(variant = variant).order_by('-second_check_date')

	return render (request, 'acmg_db/view_variant.html', {'variant': variant, 'classifications': classifications})

@transaction.atomic
@login_required
def panels(request):
	panels = Panel.objects.all().order_by('panel')
	form = NewPanelForm()
	context = {'panels': panels, 'form': form}

	if request.method == 'POST':

		form = NewPanelForm(request.POST)
		print(request.user)

		if form.is_valid():
			new_panel, created = Panel.objects.get_or_create(
				panel = form.cleaned_data['panel_name'],
				added_by = request.user
			)
		
		if not created:
			context['warn'] = ['Panel already exists']

	return render(request, 'acmg_db/panels.html', context)
