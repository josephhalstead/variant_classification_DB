from django.shortcuts import render, get_object_or_404, redirect
from .forms import *
from django.conf import settings
from .models import *
from .utils.variant_utils import *
from django.utils import timezone

def home(request):
	"""
	The view for the home page.

	Allows users to create a new classification for a variant.


	"""

	form = SearchForm()

	# If the user has searched for something
	if request.GET.get("search") != "" and request.GET.get("search") != None:

		search_query = request.GET.get("search")

		search_query = search_query.strip()

		variant_info = validate_variant(search_query, settings.MUTALYZER_URL, settings.MUTALYZER_BUILD )

		# If the variant has failed validation return to search screen and display error.
		if variant_info[0] == False:

			return render(request, 'acmg_db/home.html', {'form': form,
										 'error': variant_info[1][0]})
		else:

			# Add variant to DB if not already present

			# Get varaint information e.g. chr, pos, ref, alt from the input

			variant_data = process_variant(search_query)

			variant_hash = variant_data[0]
			chromosome = variant_data[1]
			position = variant_data[2]
			ref = variant_data[3]
			alt = variant_data[4]
			key = variant_data[5]

			variant, created = Variant.objects.get_or_create(
    				key = key,
    				variant_hash = variant_hash,
    				chromosome = chromosome,
    				position = position,
    				ref = ref,
    				alt = alt
					)

			# Loop through each transcript and gene in the variant info list and add to DB \
			# if we have not seen it before.
			for variant_transcript in variant_info[1]:


				gene, created = Gene.objects.get_or_create(
					name = variant_transcript[1]
					)

				transcript, created = Transcript.objects.get_or_create(
					name = variant_transcript[0].split(':')[0],
					gene = gene
					)
				
				transcript_variant, created = TranscriptVariant.objects.get_or_create(
					variant = variant,
					transcript = transcript,
					hgvs_c = variant_transcript[0]
					)


			new_classication = Classification.objects.create(
				variant= variant,
				creation_date = timezone.now(),
				user_creator = request.user,
				status = '0'
				)

			new_classication.save()

			new_classication.initiate_classification()


			return redirect(new_classification, new_classication.pk)


	return render(request, 'acmg_db/home.html', {'form': form, 'error': None})



def new_classification(request, pk):
	"""
	Page for entering new classifications


	"""

	classification = get_object_or_404(Classification, pk=pk)

	answers = ClassificationAnswer.objects.filter(classification=classification)




	return render(request, 'acmg_db/new_classifications.html', {'answers': answers})




