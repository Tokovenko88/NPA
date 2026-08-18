import json
import os
from datetime import datetime, timedelta
import copy
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE_DIR, 'work', 'source', '269.json'), 'r', encoding='utf-8') as f:
    data = json.load(f)
with open(os.path.join(BASE_DIR, 'work', 'source', '380.json'), 'r', encoding='utf-8') as f:
    source = json.load(f)

valid_from_dt = datetime.strptime('15.12.2017', '%d.%m.%Y').date()
valid_from_str = valid_from_dt.strftime('%d.%m.%Y')
valid_to_prev = (valid_from_dt - timedelta(days=1)).strftime('%d.%m.%Y')
modified_by_id = source.get('npa_id', '33699')

SOURCE_MODIFIED_BY = {
    'head': '33699_article_1_point_1',
    '16012_article_1': '33699_article_1_point_2',
    '16012_article_2': '33699_article_1_point_3',
    '16012_article_3': '33699_article_1_point_4',
    '16012_article_4': '33699_article_1_point_5',
    '16012_article_5': '33699_article_1_point_6',
    '16012_article_5.1': '33699_article_1_point_7',
    '16012_article_5.2': '33699_article_1_point_7',
    '16012_article_6': '33699_article_1_point_8',
    '16012_article_7': '33699_article_1_point_9',
    '16012_article_8': '33699_article_1_point_10',
}

def get_modified_by(target_id):
    return SOURCE_MODIFIED_BY.get(target_id, modified_by_id)

def get_active_revision(item):
    for rev in item.get('revisions', []):
        if rev.get('valid_to') is None:
            return rev
    return item['revisions'][-1] if item['revisions'] else None

def close_revision(item, date_str):
    active = get_active_revision(item)
    if active:
        active['valid_to'] = date_str

def new_revision(item, mod_type, modified_by, body, valid_from=None):
    rev = {
        'valid_from': valid_from if valid_from else valid_from_str,
        'valid_to': None,
        'mod_type': mod_type,
        'modified_by_id': modified_by,
        'body': body
    }
    item['revisions'].append(rev)
    return rev

def find_item(data, item_id):
    def recurse(items):
        for item in items:
            if item.get('item_id') == item_id:
                return item
            if 'item_children' in item:
                found = recurse(item['item_children'])
                if found:
                    return found
        return None
    return recurse(data.get('npa_items_revision', []))

def strip_leading_number(html_text, number):
    number = str(number).rstrip('.)')
    escaped = re.escape(number)
    pattern = re.compile(r'^(\s*<[^>]*>\s*)?' + escaped + r'[.)]\s*', re.IGNORECASE)
    return pattern.sub(lambda m: m.group(1) if m.group(1) else '', html_text)

def para(html, order=1):
    return {'type': 'paragraph', 'html_text': html, 'order': order}

def child_ref(item_id, order=1):
    return {'type': 'child_ref', 'item_id': item_id, 'order': order}

def set_item_ids(item, parent_id):
    if not item.get('item_id'):
        num = str(item.get('item_number', '')).rstrip(')').replace('.', '_')
        if item.get('item_type') == 'article' and parent_id.startswith('16012_article_'):
            parent_num = parent_id.split('_')[-1]
            if num.startswith(parent_num + '_'):
                num = num[len(parent_num) + 1:]
            item['item_id'] = parent_id + '_' + num
        else:
            item['item_id'] = parent_id + '_' + item['item_type'] + '_' + num
    for child in item.get('item_children', []):
        set_item_ids(child, item['item_id'])

def update_element_new_redaction(element, new_body, modified_by, mod_type='new_redaction', strip_number=None):
    close_revision(element, valid_to_prev)
    for i, b in enumerate(new_body, 1):
        if b.get('type') == 'paragraph' and strip_number is not None:
            b['html_text'] = strip_leading_number(b.get('html_text', ''), strip_number)
        b['order'] = i
    new_revision(element, mod_type, modified_by, new_body)

def create_new_child(number, level, item_type, body_text, modified_by, parent_id, mod_type='new_redaction'):
    body = [para(body_text)]
    item = {
        'item_id': None,
        'item_type': item_type,
        'item_number': number,
        'item_level': level,
        'revisions': [],
        'item_children': [],
    }
    for i, b in enumerate(body, 1):
        if b.get('type') == 'paragraph':
            b['html_text'] = strip_leading_number(b.get('html_text', ''), number)
        b['order'] = i
    new_revision(item, mod_type, modified_by, body)
    set_item_ids(item, parent_id)
    return item

def find_old_child(old_children, item_type, item_number):
    for child in old_children:
        if child.get('item_type') == item_type and child.get('item_number') == str(item_number):
            return child
    return None

# ============================================================
# 1. Update law title
# ============================================================
head_rev = data.get('head_revision', [])
if head_rev:
    close_revision({'revisions': head_rev}, valid_to_prev)
    head_rev.append({
        'npa_head': 'О предоставлении земельных участков, находящихся в собственности города Севастополя, отдельным категориям граждан в собственность бесплатно',
        'mod_type': 'new_redaction',
        'modified_by_id': get_modified_by('head'),
        'valid_from': valid_from_str
    })
    data['head_revision'] = head_rev
print("Updated law title")

# ============================================================
# 2. Article 1 new_redaction
# ============================================================
art1 = find_item(data, '16012_article_1')
if art1:
    close_revision(art1, valid_to_prev)
    body1 = [para('<p class="justifyfull">Настоящий Закон устанавливает условия и порядок предоставления земельных участков, находящихся в собственности города Севастополя (далее – земельные участки), отдельным категориям граждан в собственность бесплатно, основания для отказа в данном предоставлении, порядок постановки отдельных категорий граждан на учет в качестве лиц, имеющих право на предоставление земельных участков в собственность бесплатно (далее – учет), основания снятия граждан с данного учета, а также предельные размеры земельных участков, предоставляемых отдельным категориям граждан в собственность бесплатно.</p>')]
    art1['item_children'] = []
    update_element_new_redaction(art1, body1, get_modified_by('16012_article_1'))
    print("Article 1 updated")

# ============================================================
# 3. Article 2 new_redaction
# ============================================================
art2 = find_item(data, '16012_article_2')
if art2:
    close_revision(art2, valid_to_prev)
    old_children = art2.get('item_children', [])
    for child in old_children:
        close_revision(child, valid_to_prev)
    body2 = [para('<p class="justifyfull">В собственность бесплатно отдельным категориям граждан могут быть предоставлены однократно земельные участки с видом разрешенного пользования «для индивидуального жилищного строительства».</p>')]
    art2['item_children'] = []
    update_element_new_redaction(art2, body2, get_modified_by('16012_article_2'))
    print("Article 2 updated")

# ============================================================
# 4. Article 3 new_redaction
# ============================================================
art3 = find_item(data, '16012_article_3')
if art3:
    close_revision(art3, valid_to_prev)
    old_children = art3.get('item_children', [])
    for child in old_children:
        close_revision(child, valid_to_prev)
    
    p1 = find_old_child(old_children, 'point', '1)')
    if p1:
        update_element_new_redaction(p1, [para('<p class="justifyfull">имеющих трех и более детей в возрасте до 18 лет, в том числе усыновленных (удочеренных), находящихся под опекой или попечительством, а также совершеннолетних детей в возрасте до 23 лет, обучающихся в общеобразовательных организациях, профессиональных образовательных организациях и образовательных организациях высшего образования по очной форме обучения, при условии совместного проживания гражданина и его детей;</p>')], get_modified_by('16012_article_3'), strip_number='1)')
    else:
        p1 = create_new_child('1)', 2, 'point', '<p class="justifyfull">имеющих трех и более детей...</p>', get_modified_by('16012_article_3'), '16012_article_3')
        old_children.append(p1)
    
    p2 = find_old_child(old_children, 'point', '2)')
    if p2:
        update_element_new_redaction(p2, [para('<p class="justifyfull">подвергшихся политическим репрессиям и принудительно выселенных из мест проживания в связи с репрессиями и впоследствии реабилитированных.</p>')], get_modified_by('16012_article_3'), strip_number='2)')
    else:
        p2 = create_new_child('2)', 2, 'point', '<p class="justifyfull">подвергшихся политическим репрессиям...</p>', get_modified_by('16012_article_3'), '16012_article_3')
        old_children.append(p2)
    
    art3['item_children'] = [p1, p2]
    body3 = [
        para('<p class="justifyfull">К отдельным категориям граждан, имеющих право на приобретение земельных участков в собственность бесплатно, относятся граждане из числа лиц:</p>'),
        child_ref(p1['item_id']),
        child_ref(p2['item_id'])
    ]
    update_element_new_redaction(art3, body3, get_modified_by('16012_article_3'))
    print("Article 3 updated")

# ============================================================
# 5. Article 4 new_redaction
# ============================================================
art4 = find_item(data, '16012_article_4')
if art4:
    close_revision(art4, valid_to_prev)
    old_children = art4.get('item_children', [])
    for child in old_children:
        close_revision(child, valid_to_prev)
    
    part1 = create_new_child('1', 2, 'part',
        '<p class="justifyfull">1. Основанием для предоставления земельных участков гражданам, относящимся к категориям, установленным статьей 3 настоящего Закона, в собственность бесплатно являются следующие условия:</p>',
        get_modified_by('16012_article_4'), '16012_article_4', mod_type='add')
    sub1 = create_new_child('1)', 3, 'point',
        '<p class="justifyfull">1) гражданин принят на учет в порядке, установленном настоящим Законом;</p>',
        get_modified_by('16012_article_4'), part1['item_id'], mod_type='add')
    sub2 = create_new_child('2)', 3, 'point',
        '<p class="justifyfull">2) гражданин, его супруг (супруга) и несовершеннолетние дети не имеют иного земельного участка в собственности либо в пользовании (аренде) и в их отношении не принималось решение о предоставлении (передаче) земельного участка в собственность бесплатно или решение, на основании которого возможно завершение оформления права на земельный участок для индивидуального жилищного строительства в соответствии с федеральным законодательством и законодательством города Севастополя;</p>',
        get_modified_by('16012_article_4'), part1['item_id'], mod_type='add')
    sub3 = create_new_child('3)', 3, 'point',
        '<p class="justifyfull">3) гражданин постоянно проживает на территории города Севастополя в течение 10 лет до подачи заявления о постановке на учет (далее – заявление);</p>',
        get_modified_by('16012_article_4'), part1['item_id'], mod_type='add')
    sub4 = create_new_child('4)', 3, 'point',
        '<p class="justifyfull">4) гражданин, его супруг (супруга), несовершеннолетние дети не имеют в собственности, а также в пользовании на условиях договора социального найма жилого помещения, в том числе жилого дома, либо имеющееся на вышеуказанных правах жилое помещение обеспечивает каждого из членов семьи частью общей площади менее учетной нормы площади жилого помещения, установленной законодательством города Севастополя;</p>',
        get_modified_by('16012_article_4'), part1['item_id'], mod_type='add')
    sub5 = create_new_child('5)', 3, 'point',
        '<p class="justifyfull">5) гражданин и (или) его супруг (супруга) состоят на учете в качестве нуждающихся в жилых помещениях или у таких граждан имеются основания для их постановки на данный учет.</p>',
        get_modified_by('16012_article_4'), part1['item_id'], mod_type='add')
    part1['item_children'] = [sub1, sub2, sub3, sub4, sub5]
    
    part2 = create_new_child('2', 2, 'part',
        '<p class="justifyfull">2. При наличии у гражданина, его супруга (супруги), несовершеннолетних детей нескольких жилых помещений, занимаемых по договорам социального найма и (или) принадлежащих им на праве собственности, определение уровня обеспеченности общей площадью жилого помещения осуществляется исходя из суммарной общей площади, состоящей из площади жилых помещений, занимаемых ими по договорам социального найма, и площади, приходящейся на доли гражданина, его супруга (супруги), несовершеннолетних детей, в жилых помещениях, принадлежащих им на праве собственности.</p>',
        get_modified_by('16012_article_4'), '16012_article_4', mod_type='add')
    
    art4['item_children'] = [part1, part2]
    body4 = [
        child_ref(part1['item_id']),
        child_ref(part2['item_id'])
    ]
    art4['head_revisions'] = [{'head_text': 'Условия предоставления земельных участков в собственность бесплатно'}]
    update_element_new_redaction(art4, body4, get_modified_by('16012_article_4'))
    print("Article 4 updated")

# ============================================================
# 6. Article 5 new_redaction + add 5.1 and 5.2
# ============================================================
art5 = find_item(data, '16012_article_5')
if art5:
    close_revision(art5, valid_to_prev)
    old_children = art5.get('item_children', [])
    for child in old_children:
        close_revision(child, valid_to_prev)
    
    new_part_texts = {
        '1': '<p class="justifyfull">1. Учет, в соответствии с настоящим Законом, осуществляется исполнительным органом государственной власти города Севастополя, уполномоченным в сфере имущественных и земельных отношений (далее – уполномоченный орган), на основании заявлений граждан, относящихся к категориям граждан, установленным статьей 3 настоящего Закона.</p>',
        '2': '<p class="justifyfull">2. Для постановки на учет гражданин подает заявление в письменной форме, к которому прилагаются документы, подтверждающие основания, соответствующие условиям, указанным в статье 4 настоящего Закона. Перечень прилагаемых документов устанавливается Правительством Севастополя.</p>',
        '3': '<p class="justifyfull">3. Не позднее чем через 45 календарных дней со дня подачи гражданином заявления уполномоченный орган принимает решение о принятии (об отказе в принятии) гражданина на учет.</p>',
        '4': '<p class="justifyfull">4. Отсутствие на территории города Севастополя земельных участков, свободных от прав третьих лиц и прошедших государственный кадастровый учет, не является основанием для отказа в постановке на учет.</p>',
        '5': '<p class="justifyfull">5. В случае смерти либо объявления умершим на основании вступившего в законную силу решения суда состоящего на учете гражданина из категории граждан, установленных пунктом 1 статьи 3 настоящего Закона, постановке на учет с сохранением очередности такого гражданина подлежит второй родитель (усыновитель, опекун, попечитель).</p>',
        '6': '<p class="justifyfull">6. Учет граждан, в отношении которых принято решение о постановке на учет, ведется уполномоченным органом в Книге учета граждан в целях последующего предоставления земельных участков в собственность бесплатно (далее – Книга учета). Форма Книги учета устанавливается нормативным правовым актом уполномоченного органа.</p>',
        '7': '<p class="justifyfull">7. Очередность постановки граждан на учет определяется по предоставлению ими заявлений начиная с самого раннего по времени и дате подачи.</p>',
    }
    new_active_parts = []
    for num in ['1', '2', '3', '4', '5', '6', '7']:
        child = find_old_child(old_children, 'part', num)
        if child:
            update_element_new_redaction(child, [para(new_part_texts[num])], get_modified_by('16012_article_5'), strip_number=num)
            new_active_parts.append(child)
        else:
            p = create_new_child(num, 2, 'part', new_part_texts[num], get_modified_by('16012_article_5'), '16012_article_5')
            old_children.append(p)
            new_active_parts.append(p)
    
    # Add article 5.1
    art51 = {
        'item_type': 'article',
        'item_number': '5.1',
        'item_level': art5['item_level'] + 1,
        'revisions': [],
        'item_children': [],
        'head_revisions': [{'head_text': 'Основания для отказа в постановке граждан на учет'}]
    }
    p51_1 = create_new_child('1)', 3, 'point',
        '<p class="justifyfull">1) отсутствие права на предоставление земельного участка в собственность бесплатно в соответствии с настоящим Законом;</p>',
        get_modified_by('16012_article_5.1'), '16012_article_5_1', mod_type='add')
    p51_2 = create_new_child('2)', 3, 'point',
        '<p class="justifyfull">2) непредставление или представление не в полном объеме документов, предусмотренных частью 2 статьи 5 настоящего Закона, либо представление документов, содержащих недостоверные сведения.</p>',
        get_modified_by('16012_article_5.1'), '16012_article_5_1', mod_type='add')
    art51['item_children'] = [p51_1, p51_2]
    set_item_ids(art51, '16012_article_5')
    body51 = [
        para('<p class="justifyfull">Основанием для отказа в постановке граждан на учет является:</p>'),
        child_ref(p51_1['item_id']),
        child_ref(p51_2['item_id'])
    ]
    update_element_new_redaction(art51, body51, get_modified_by('16012_article_5.1'), mod_type='add')
    
    # Add article 5.2
    art52 = {
        'item_type': 'article',
        'item_number': '5.2',
        'item_level': art5['item_level'] + 1,
        'revisions': [],
        'item_children': [],
        'head_revisions': [{'head_text': 'Основания для снятия граждан с учета'}]
    }
    p52_1 = create_new_child('1)', 3, 'point',
        '<p class="justifyfull">1) подача гражданином заявления о снятии с учета;</p>',
        get_modified_by('16012_article_5.2'), '16012_article_5_2', mod_type='add')
    p52_2 = create_new_child('2)', 3, 'point',
        '<p class="justifyfull">2) утрата гражданином оснований, дающих ему право на получение земельного участка в собственность бесплатно, указанных в настоящем Законе;</p>',
        get_modified_by('16012_article_5.2'), '16012_article_5_2', mod_type='add')
    p52_3 = create_new_child('3)', 3, 'point',
        '<p class="justifyfull">3) выявление сведений, не соответствующих действительности, в документах, представленных гражданином для постановки на учет;</p>',
        get_modified_by('16012_article_5.2'), '16012_article_5_2', mod_type='add')
    p52_4 = create_new_child('4)', 3, 'point',
        '<p class="justifyfull">4) получение гражданином земельного участка в собственность бесплатно в соответствии с настоящим Законом;</p>',
        get_modified_by('16012_article_5.2'), '16012_article_5_2', mod_type='add')
    p52_5 = create_new_child('5)', 3, 'point',
        '<p class="justifyfull">5) выезд гражданина на постоянное место жительства в другой субъект Российской Федерации или территорию иностранного государства.</p>',
        get_modified_by('16012_article_5.2'), '16012_article_5_2', mod_type='add')
    art52['item_children'] = [p52_1, p52_2, p52_3, p52_4, p52_5]
    set_item_ids(art52, '16012_article_5')
    body52 = [
        para('<p class="justifyfull">Основанием для снятия гражданина с учета является:</p>'),
        child_ref(p52_1['item_id']),
        child_ref(p52_2['item_id']),
        child_ref(p52_3['item_id']),
        child_ref(p52_4['item_id']),
        child_ref(p52_5['item_id'])
    ]
    update_element_new_redaction(art52, body52, get_modified_by('16012_article_5.2'), mod_type='add')
    
    art5['item_children'] = new_active_parts + [art51, art52]
    body5 = [child_ref(p['item_id']) for p in new_active_parts]
    body5.append(child_ref(art51['item_id']))
    body5.append(child_ref(art52['item_id']))
    update_element_new_redaction(art5, body5, get_modified_by('16012_article_5'))
    print("Article 5 updated")

# ============================================================
# 7. Article 6 new_redaction
# ============================================================
art6 = find_item(data, '16012_article_6')
if art6:
    close_revision(art6, valid_to_prev)
    old_children = art6.get('item_children', [])
    for child in old_children:
        close_revision(child, valid_to_prev)
    
    part_texts6 = [
        ('1', '<p class="justifyfull">1. Земельные участки предоставляются отдельным категориям граждан, состоящим на учете, в собственность бесплатно из состава Единого перечня земельных участков, предназначенных для предоставления в собственность бесплатно отдельным категориям граждан, указанным в статье 3 настоящего Закона (далее – Единый перечень).</p>'),
        ('2', '<p class="justifyfull">2. Единый перечень составляется уполномоченным органом и обновляется им ежеквартально не позднее последнего дня квартала. Единый перечень содержит информацию об адресе, кадастровом номере, виде разрешенного использования и площади земельных участков.</p>'),
        ('3', '<p class="justifyfull">3. Сведения о земельных участках, включенных в Единый перечень, подлежат публикации на официальном сайте уполномоченного органа в информационно-телекоммуникационной сети «Интернет» не позднее 14 дней после начала квартала, следующего за кварталом утверждения (обновления) Единого перечня.</p>'),
        ('4', '<p class="justifyfull">4. Форма Единого перечня устанавливается уполномоченным органом.</p>')
    ]
    new_active_parts6 = []
    for num, text in part_texts6:
        child = find_old_child(old_children, 'part', num)
        if child:
            update_element_new_redaction(child, [para(text)], get_modified_by('16012_article_6'), strip_number=num)
            new_active_parts6.append(child)
        else:
            p = create_new_child(num, 2, 'part', text, get_modified_by('16012_article_6'), '16012_article_6')
            old_children.append(p)
            new_active_parts6.append(p)
    art6['item_children'] = new_active_parts6
    body6 = [child_ref(p['item_id']) for p in new_active_parts6]
    update_element_new_redaction(art6, body6, get_modified_by('16012_article_6'))
    print("Article 6 updated")

# ============================================================
# 8. Article 7 new_redaction
# ============================================================
art7 = find_item(data, '16012_article_7')
if art7:
    close_revision(art7, valid_to_prev)
    old_children = art7.get('item_children', [])
    for child in old_children:
        close_revision(child, valid_to_prev)
    
    part_texts7 = [
        ('1', '<p class="justifyfull">1. Земельные участки предоставляются отдельным категориям граждан, состоящим на учете (далее – заявитель), в собственность бесплатно в порядке очередности подачи ими заявлений.</p>'),
        ('2', '<p class="justifyfull">2. При наличии в Едином перечне земельного участка (земельных участков) с видом разрешенного использования, установленным в статье 2 настоящего Закона, уполномоченный орган в течение 30 дней проверяет условия, явившиеся основанием для постановки заявителя на учет в соответствии со статьей 4 настоящего Закона, путем направления межведомственного запроса о предоставлении необходимых сведений и документов.</p>'),
        ('3', '<p class="justifyfull">3. После получения ответа на межведомственный запрос уполномоченный орган направляет заявителю заказным письмом уведомление о возможности предоставления земельного участка в собственность бесплатно. В случае если после получения запрошенных сведений будет выявлено их несоответствие условиям, установленным статьей 4 настоящего Закона, уполномоченный орган снимает его с учета.</p>'),
        ('4', '<p class="justifyfull">4. Заявитель в течение 10 календарных дней со дня получения уведомления, указанного в части 3 настоящей статьи, направляет в уполномоченный орган заявление о согласии на приобретение земельного участка в собственность бесплатно или об отказе от его приобретения.</p>'),
        ('5', '<p class="justifyfull">5. Заявитель, не направивший в уполномоченный орган в установленный срок заявление о согласии на приобретение земельного участка в собственность бесплатно или об отказе от его приобретения, сохраняет за собой право на получение земельного участка в соответствии с настоящим Законом. В этом случае земельный участок, который был предложен заявителю, предлагается другим состоящим на учете гражданам в порядке очередности.</p>'),
        ('6', '<p class="justifyfull">6. В случае отказа от приобретения земельного участка в собственность бесплатно заявитель сохраняет за собой право на получение иного земельного участка в соответствии с настоящим Законом. В этом случае земельный участок, от приобретения которого заявитель отказался, предлагается другим состоящим на учете гражданам в порядке очередности.</p>'),
        ('7', '<p class="justifyfull">7. Решение о предоставлении заявителю земельного участка в собственность бесплатно является основанием для государственной регистрации права собственности на земельный участок.</p>'),
        ('8', '<p class="justifyfull">8. В случае предоставления земельного участка отдельным категориям граждан, указанным в пункте 1 статьи 3 настоящего Закона, в собственность бесплатно земельный участок подлежит оформлению на праве общей долевой собственности в равных долях на каждого члена семьи, указанного в пункте 1 статьи 3 настоящего Закона.</p>'),
        ('9', '<p class="justifyfull">9. В случае выявления недостоверных сведений в представленных документах, послуживших основанием для постановки гражданина на учет, после получения гражданином земельного участка в собственность бесплатно, решение о предоставлении земельного участка подлежит отмене уполномоченным органом, а земельный участок – возврату в собственность города Севастополя.</p>')
    ]
    new_active_parts7 = []
    for num, text in part_texts7:
        child = find_old_child(old_children, 'part', num)
        if child:
            update_element_new_redaction(child, [para(text)], get_modified_by('16012_article_7'), strip_number=num)
            new_active_parts7.append(child)
        else:
            p = create_new_child(num, 2, 'part', text, get_modified_by('16012_article_7'), '16012_article_7')
            old_children.append(p)
            new_active_parts7.append(p)
    art7['item_children'] = new_active_parts7
    body7 = [child_ref(p['item_id']) for p in new_active_parts7]
    update_element_new_redaction(art7, body7, get_modified_by('16012_article_7'))
    print("Article 7 updated")

# ============================================================
# 9. Article 8 new_redaction
# ============================================================
art8 = find_item(data, '16012_article_8')
if art8:
    close_revision(art8, valid_to_prev)
    old_children = art8.get('item_children', [])
    for child in old_children:
        close_revision(child, valid_to_prev)
    body8 = [para('<p class="justifyfull">Для земельных участков, предоставляемых в соответствии с настоящим Законом для индивидуального жилищного строительства в собственность бесплатно, устанавливаются следующие предельные (минимальные и максимальные) размеры – от 0,04 до 0,10 гектара.</p>')]
    art8['item_children'] = []
    update_element_new_redaction(art8, body8, get_modified_by('16012_article_8'))
    print("Article 8 updated")

# ============================================================
# 10. Add revision_info
# ============================================================
rev_info = {
    'revision_id': modified_by_id,
    'revision_number': source.get('npa_number', ''),
    'revision_date_reg': source.get('date_signed', ''),
    'revision_date_valid': valid_from_str,
    'revision_url': source.get('npa_url', '')
}
if 'revision_info' not in data:
    data['revision_info'] = []
if not any(r.get('revision_id') == rev_info['revision_id'] for r in data['revision_info']):
    data['revision_info'].append(rev_info)

# ============================================================
# 11. Save result
# ============================================================
result_filename = '269_2016_07_27_izm_380_2017_12_04.json'
result_path = os.path.join(BASE_DIR, 'work', 'results') + os.sep + result_filename
with open(result_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"\nResult saved to {result_path}")

# Verification
print("\n=== VERIFICATION ===")
print(f"head_revision count: {len(data.get('head_revision', []))}")
for hr in data.get('head_revision', []):
    print(f"  - {hr.get('npa_head', '')[:60]}... valid_to={hr.get('valid_to')} mod_type={hr.get('mod_type')} modified_by_id={hr.get('modified_by_id')}")

print(f"\nnpa_items count: {len(data.get('npa_items_revision', []))}")
for item in data.get('npa_items_revision', []):
    aid = item.get('item_id')
    atype = item.get('item_type')
    anum = item.get('item_number')
    children = item.get('item_children', [])
    revs = item.get('revisions', [])
    active = [r for r in revs if r.get('valid_to') is None]
    print(f"  {aid} ({atype} {anum})")
    print(f"    children: {len(children)} -> {[c.get('item_id') for c in children]}")
    if active:
        print(f"    active mod_type: {active[0].get('mod_type')}")
        print(f"    active modified_by_id: {active[0].get('modified_by_id')}")
        print(f"    active body types: {[b.get('type') for b in active[0].get('body', [])]}")
    print(f"    revisions count: {len(revs)}")
    for rev in revs:
        print(f"      valid_from={rev.get('valid_from')} valid_to={rev.get('valid_to')} mod_type={rev.get('mod_type')} modified_by_id={rev.get('modified_by_id')}")
