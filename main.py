from lxml import etree
import xmltodict
import json
import uuid
import pprint

pp = pprint.PrettyPrinter(indent=4)

# Calculates the line number for a requested word element based on its document position.
def calculate_line_number(word_element):
    # Pick up the page so that we can math out the word's y position based on the page's height.
    page = next(word_element.iterancestors(tag='page'))
    # This is getting kinda weird.  But if this is a superscript, then make this end up on the previous word's line
    word_position = word_element.attrib.get('pos', 'regular')
    if word_position == 'regular':
        word_corrected_y = float(page.attrib['height']) - float(word_element.attrib['lly'])
    else:
        word_index = word_element.getparent().index(word_element)
        previous_word = next(word_element.itersiblings(tag='word', preceding=True)) if word_index > 0 else word_element
        word_corrected_y = float(page.attrib['height']) - float(previous_word.attrib['lly'])

    return (round(pt2char(word_corrected_y)))

# we are getting in the page element, an hash indicating the line-numbers and their associated text elements,
#   and the cursor position relative to the entire document.
def render_page_text_from_lines(page, page_lines, document_cursor_position=0):
    # Since we will only receive entries in page_lines that contain content, we will need to fill the empty lines with
    #   whitespace in order to reconstruct the visual layout.
    # So, we start with the page height and construct a fill dict with all the line indices.  Then we "update" to overwrite
    #   the fill dict with the page_lines data.
    page_height = float(page.attrib['height'])
    max_page_lines = round(pt2char(page_height))
    fill_dict = dict.fromkeys(list(range(1, max_page_lines)), [])
    fill_dict.update(page_lines)
    #
    rendered_page_cursor_position = 0
    rendered_page_contents = ''
    render_page_lines = fill_dict.values()
    for line in render_page_lines:
        for text_element in line:
            word = text_element.getparent()
            left_padding = int(word.attrib['leftPadding'])
            trailing_space = ' ' if word.attrib['spaceAfter'] == 'true' else ''
            left_padded_string_length = left_padding + len(text_element.text)
            render_text_element = text_element.text.rjust(left_padded_string_length)
            render_text_element += trailing_space

            rendered_page_contents += render_text_element

            rendered_page_cursor_position += len(render_text_element)
            document_cursor_position += len(render_text_element)
            page_word_start_position = rendered_page_cursor_position - len(text_element.text)
            doc_word_start_position = document_cursor_position - len(text_element.text)

            word.set('adjustedPageCharPos', str(page_word_start_position))
            word.set('adjustedDocumentCharPos', str(doc_word_start_position))
            word.set('spaceOffset', str(len(trailing_space) + left_padding))
            word.set('wordLength', str(len(text_element.text)))

        rendered_page_contents += '\n'
        rendered_page_cursor_position += 1
        document_cursor_position += 1

    rendered_page_contents += '\f'
    return rendered_page_contents

# DTP points (pt) to character.  Assumes 72dpi
def pt2char(points):
    return points * (1/6)

# DTP points (pt) to pixels.
def pt2px(points):
    return points * (1 + 1/3)

def extract_text_from_xdpf_xml(xml_file_path):
    extracted_text_string = ""

    # Open the xml file
    xml_doc = etree.parse(xml_file_path)
    xml_doc_root = xml_doc.getroot()

    # XPDF's structure is page > column > paragraph > line > word
    #   https://www.glyphandcog.com/manuals/PDFdeconstruct/xml-text.html

    # pick up all the pages in this document
    pages = xml_doc_root.xpath('//page')

    # for each page, let's process the words
    for page_number, page in enumerate(pages):
        page_word_texts = page.xpath('./column/paragraph/line/word/text')
        page_lines = {}

        if len(page_word_texts) > 0:
            # Sort the words on this page by 'charPos'.  This will give us the text contents in "reading order" vs.
            #   the xml's default ordering of elements which is in "content stream order".
            sorted_page_words = sorted(page_word_texts, key=lambda w: int(w.getparent().attrib['charPos']), reverse=False)
            # Now, let's process the text elements
            for text_element_index, text_element in enumerate(sorted_page_words):
                # Get the "word" container for this text element
                word = text_element.getparent()
                word_index = word.getparent().index(word)

                # Get the line number where this word will appear.  This is important in cases with "table like" layouts
                #   and column'd data etc.
                line_number = calculate_line_number(word)

                # Calculate the left padding on this piece of text.  This will acocunt for margins, and other types of
                #   whitespace based formatting.
                left_padding = round((pt2char(float(word.attrib['llx'])))) if word_index == 0 else 0

                # print(f'leftpadding: {left_padding}, text: {text_element.text}, index:{word.getparent().index(word)}, llx: {pt2char(float(word.attrib["llx"]))}, lly: {float(word.attrib["lly"])}, line number: {line_number}, page char count: {page_character_counter}, leftpadding: {left_padded_string_length} :{text_element.text.rjust(left_padded_string_length)}:\n\n')

                # Let's supplement the xpdf element attributes with a few more that we have calculated
                word.set('leftPadding', str(left_padding))
                word.set('lineNumber', str(line_number))
                word.set('readingOrder', str(text_element_index))
                # Assign a uuid to this word.
                word.set('uuid', str(uuid.uuid4()))

                # Append this text_element to page_lines.  `setdefault` will take care of initializing the list at the
                #   requested line_number index.
                page_lines.setdefault(line_number, []).append(text_element)

            # page break
            #   Now's a good time to generate the text content
            extracted_text_string += render_page_text_from_lines(page, page_lines, len(extracted_text_string))

    # Write the updated xml to file
    xml_doc.write(xml_file_path+'.formatted.xml')

    #convert the xml to json
    json_output_path = xml_file_path + ".json"
    file_handler = open(json_output_path, 'w')
    file_handler.write(json.dumps(xmltodict.parse(etree.tostring(xml_doc_root), force_list={'line'})))
    file_handler.close()

    return extracted_text_string


def locate_elements_in_xml(xml_file_path, start_char_pos, end_char_pos):
    # Open the xml file
    xml_doc = etree.parse(xml_file_path)
    xml_doc_root = xml_doc.getroot()

    # get the text elements between the requested char positions
    xpath_expr = str(f'//word[@adjustedDocumentCharPos >= {start_char_pos} and @adjustedDocumentCharPos <= {end_char_pos} ]')
    matched_words = xml_doc_root.xpath(xpath_expr)
    sorted_words = sorted(matched_words, key=lambda w: int(w.attrib['adjustedDocumentCharPos']), reverse=False)

    # Let's collect a sort of rectangle from the coordinates of the matching elements
    # This will essentially create a sort of viewport that will define our "region of interest" in the context of the
    #   visual PDF.
    # We can then use this viewport rectangle to either identify DOM elements that fall inside of it or perhaps even
    # draw something in an SVG layer based on these coordinates.
    x_coords = []
    y_coords = []
    for word in sorted_words:
        page = next(word.iterancestors(tag='page'))
        word_corrected_y = float(page.attrib['height']) - float(word.attrib['ury'])

        x_coords.append(float(word.attrib['llx']))
        y_coords.append(word_corrected_y)

    # pp.pprint(x_coords)
    # pp.pprint(y_coords)
    #   The viewport would simply find the min/max x and y bounds for the matched word elements.
    #   Since we intend to send this to the browser, i'm doing a pt2px conversion here.  Could easily move the conversion
    #       step elsewhere.
    return {'xmin': pt2px(min(x_coords)), 'xmax': pt2px(max(x_coords)), 'ymin': pt2px(min(y_coords)), 'ymax': pt2px(max(y_coords))}

def enhance_xpdf_output():
    xml_file_path = '/Users/shaheeb/Downloads/XPDF_Extraction/Affinity_Gaming_Full_time_Life_LTD.xml'
    extracted_text = extract_text_from_xdpf_xml(xml_file_path)
    extracted_text_output_path = xml_file_path + ".txt"
    file_handler = open(extracted_text_output_path, 'w')
    file_handler.write(extracted_text)
    file_handler.close()

def test_finding_text():
    xml_file_path = '/Users/shaheeb/Downloads/XPDF_Extraction/00252873_Member_Cert_Class_03.xml.formatted.xml'
    start_char_pos = 300
    end_char_pos = 375

    return locate_elements_in_xml(xml_file_path, start_char_pos, end_char_pos)