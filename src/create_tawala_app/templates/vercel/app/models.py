from django.db import models

# Create your models here.
class Portfolio(models.Model):
    image = models.ImageField(upload_to="images/")
    document = models.FileField(upload_to="documents/", blank=True, null=True)

    def get_image_url(self):
        return self.image.url
