import os
from urllib import request
from geopy.distance import geodesic
import PIL
from PIL import Image
import time
from datetime import timedelta

from tilesystem import TileSystem

TILE_SIZE = 256
OUTPUT_DIR = "./output/"


class AerialImageRetrieval(object):
    PIL.Image.MAX_IMAGE_PIXELS = None

    def __init__(self, upper_left, lower_right, zoom_level, name, tiles_url):
        self.lat1 = upper_left[0]
        self.lon1 = upper_left[1]
        self.lat2 = lower_right[0]
        self.lon2 = lower_right[1]
        self.zoom = zoom_level
        self.name = name
        self.tiles_url = tiles_url

        try:
            os.makedirs(OUTPUT_DIR)
        except FileExistsError:
            pass
        except OSError:
            raise

    def download_image(self, quadkey):
        with request.urlopen(self.tiles_url.format(quadkey)) as file:
            return Image.open(file)

    def is_valid_image(self, image):
        if not os.path.exists('null.png'):
            null_image = self.download_image(
                '11111111111111111111')  # an invalid quadkey which will download a null jpeg from Bing tile system
            null_image.save('./null.png')
        return not (image == Image.open('./null.png'))

    def retrieve(self):
        pixelX1, pixelY1 = TileSystem.latlong_to_pixelXY(self.lat1, self.lon1, self.zoom)
        pixelX2, pixelY2 = TileSystem.latlong_to_pixelXY(self.lat2, self.lon2, self.zoom)

        pixelX1, pixelX2 = min(pixelX1, pixelX2), max(pixelX1, pixelX2)
        pixelY1, pixelY2 = min(pixelY1, pixelY2), max(pixelY1, pixelY2)

        # Bounding box's two coordinates coincide at the same pixel, which is invalid for an aerial image.
        # Raise error and directly return without retrieving any valid image.
        if abs(pixelX1 - pixelX2) <= 1 or abs(pixelY1 - pixelY2) <= 1:
            print("Cannot find a valid aerial imagery for the given bounding box!")
            return

        tileX1, tileY1 = TileSystem.pixelXY_to_tileXY(pixelX1, pixelY1)
        tileX2, tileY2 = TileSystem.pixelXY_to_tileXY(pixelX2, pixelY2)

        # Stitch the tile images together
        result = Image.new('RGB', ((tileX2 - tileX1 + 1) * TILE_SIZE, (tileY2 - tileY1 + 1) * TILE_SIZE))

        # initialize a initial timestamp for remaining time estimation
        old_ts = time.time()
        avg_download_time = None
        retrieve_success = False
        for tileY in range(tileY1, tileY2 + 1):
            retrieve_success, horizontal_image = self.horizontal_retrieval_and_stitch_image(tileX1, tileX2, tileY,
                                                                                            self.zoom)
            if not retrieve_success:
                break
            result.paste(horizontal_image, (0, (tileY - tileY1) * TILE_SIZE))
            ts = time.time()
            timespan = ts - old_ts
            local_prevision = timespan * (tileY2 - tileY)
            # if it's not the first cycle
            if avg_download_time:
                # make and average between past averages and a prediction made on last download time
                historical_prevision = avg_download_time - timespan
                avg_download_time = (local_prevision + historical_prevision) / 2
            else:
                # if it's the first cycle just use a prediction made on last download time
                avg_download_time = local_prevision
            # remove microseconds from print
            string_remaining_time = str(timedelta(seconds=avg_download_time)).split(".", 1)[0]
            print("Remaining time " + string_remaining_time)
            old_ts = ts

        if not retrieve_success:
            return

        # Crop the image based on the given bounding box
        leftup_cornerX, leftup_cornerY = TileSystem.tileXY_to_pixelXY(tileX1, tileY1)
        retrieve_image = result.crop(
            (pixelX1 - leftup_cornerX, pixelY1 - leftup_cornerY, pixelX2 - leftup_cornerX, pixelY2 - leftup_cornerY))
        filename = "{0}_{1}.jpeg".format(self.name, self.zoom)
        file = os.path.join(OUTPUT_DIR, filename)
        retrieve_image.save(file)
        print("Arial stored in file {0}".format(filename))

    def horizontal_retrieval_and_stitch_image(self, tileX_start, tileX_end, tileY, level):
        """Horizontally retrieve tile images and then stitch them together,
        start from tileX_start and end at tileX_end, tileY will remain the same
        
        Arguments:
            tileX_start {[int]} -- [the starting tileX index]
            tileX_end {[int]} -- [the ending tileX index]
            tileY {[int]} -- [the tileY index]
            level {[int]} -- [level used to retrieve image]
        
        Returns:
            [boolean, Image] -- [whether such retrieval is successful; If successful, returning the stitched image, otherwise None]
        """

        imagelist = []
        for tileX in range(tileX_start, tileX_end + 1):
            quadkey = TileSystem.tileXY_to_quadkey(tileX, tileY, level)
            image = self.download_image(quadkey)
            if self.is_valid_image(image):
                imagelist.append(image)
            else:
                # print(quadkey)
                print("Cannot find tile image at level {0} for tile coordinate ({1}, {2})".format(level, tileX, tileY))
                return False, None
        result = Image.new('RGB', (len(imagelist) * TILE_SIZE, TILE_SIZE))
        for i, image in enumerate(imagelist):
            result.paste(image, (i * TILE_SIZE, 0))
        return True, result


def calculate_coordinates_bounds_from_center(center, distance_vertical_meters, distance_horizontal_meters):
    upper_left = geodesic(meters=distance_horizontal_meters).destination(
        geodesic(meters=distance_vertical_meters).destination(center, 0), -90)
    lower_right = geodesic(meters=distance_horizontal_meters).destination(
        geodesic(meters=distance_vertical_meters).destination(center, 180), 90)
    return (upper_left.latitude, upper_left.longitude), (lower_right.latitude, lower_right.longitude)


def calculate_larger_coordinates_rectangle_with_aspectratio_1p414(upper_left, lower_right):
    center = ((upper_left[0] + lower_right[0]) / 2, (upper_left[1] + lower_right[1]) / 2)

    # measure the rectangle's area by using the distances in the middle
    half_width = geodesic((center[0], upper_left[1]), (center[0], center[1])).meters
    half_height = geodesic((upper_left[0], center[1]), (center[0], center[1])).meters

    if half_height > half_width:
        # portrait
        height_per_width = half_height / half_width
        if height_per_width < 1.414:
            target_half_height = half_width * 1.414
            return calculate_coordinates_bounds_from_center(center, target_half_height, half_width)
        else:
            target_half_width = half_height * 1.414
            return calculate_coordinates_bounds_from_center(center, half_height, target_half_width)
    else:
        # landscape
        width_per_height = half_width / half_height
        if width_per_height < 1.414:
            target_half_width = half_height * 1.414
            return calculate_coordinates_bounds_from_center(center, half_height, target_half_width)
        else:
            target_half_height = half_width / 1.414
            return calculate_coordinates_bounds_from_center(center, target_half_height, half_width)


def calculate_area_in_square_km(upper_left, lower_right):
    center = ((upper_left[0] + lower_right[0]) / 2, (upper_left[1] + lower_right[1]) / 2)

    # measure the rectangle's area by using the distances in the middle
    width = geodesic((center[0], upper_left[1]), (center[0], center[1])).kilometers * 2
    height = geodesic((upper_left[0], center[1]), (center[0], center[1])).kilometers * 2
    return width * height


def retrieve_aerial_for(name, upper_left, lower_right, zoom, is_Aformat, bing_tiles_url):
    print("Retrieving {0} ...".format(name))
    print("Original bounds: ", (upper_left, lower_right))

    larger_rectangle = (upper_left, lower_right)
    if is_Aformat:
        larger_rectangle = calculate_larger_coordinates_rectangle_with_aspectratio_1p414(upper_left, lower_right)
        print("Ax bigger bounds: ", larger_rectangle)

    print("Total square kilometers: ", calculate_area_in_square_km(larger_rectangle[0], larger_rectangle[1]).__ceil__())

    AerialImageRetrieval(larger_rectangle[0], larger_rectangle[1], zoom,
                         name, bing_tiles_url).retrieve()


def main():
    PIL.Image.MAX_IMAGE_PIXELS = None
    retrieve_aerial_for("Burano",
                        (45.487969, 12.412582),
                        (45.482488, 12.421843),
                        20,
                        False,
                        "http://ecn.t3.tiles.virtualearth.net/tiles/a{0}.jpeg?g=14055"
                        )


if __name__ == '__main__':
    main()
