"""Shared desktop geometry and typography; sizes use Qt logical pixels, like CSS px."""
import json,re,sys
from pathlib import Path
from PySide6.QtCore import Qt,QSize,QRectF
from PySide6.QtGui import QFont,QPalette,QColor,QIcon,QPixmap,QPainter,QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget,QLabel,QFrame,QPushButton,QLineEdit,QTextEdit,QScrollArea,QVBoxLayout,QHBoxLayout,QSizePolicy,QLayout
TOKENS=json.loads((Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'ui_tokens.json').read_text(encoding='utf8'))

def action_icon(button,dark):
    name=getattr(button,'_stitch_icon_name','')
    kind='run' if button.property('nv_process_action') else 'stop' if name=='stop' or button.text().startswith('停止') else 'folder' if name=='folder' else None
    if kind is None:return
    paths={'run':'<path d="M4 12h15M13 6l6 6-6 6"/>',
           'stop':'<rect x="6" y="6" width="12" height="12" rx="2"/>',
           'folder':'<path d="M3 9V6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v2M3 9h6l2 2h11l-3 9H5a2 2 0 0 1-2-2V9z"/>'}
    p=TOKENS['dark' if dark else 'light'];color=p['onPrimary'] if kind=='run' else p['text']
    dashboard_arrow=kind=='run' and bool(button.property('nv_dashboard_action'))
    if dashboard_arrow:color='#858b94'
    dpr=button.devicePixelRatioF();pix=QPixmap(round(18*dpr),round(18*dpr));pix.setDevicePixelRatio(dpr);pix.fill(Qt.GlobalColor.transparent)
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths[kind]}</svg>'
    renderer=QSvgRenderer(svg.encode());painter=QPainter(pix);renderer.render(painter,QRectF(0,0,18,18));painter.end()
    icon=QIcon(pix)
    if dashboard_arrow:icon.addPixmap(pix,QIcon.Mode.Disabled)
    button.setIcon(icon);button.setIconSize(QSize(18,18));button.setProperty('nv_vector_action',kind)

def fold_indicator(button,angle):
    button._fold_angle=float(angle)
    dpr=button.devicePixelRatioF();pix=QPixmap(round(16*dpr),round(16*dpr));pix.setDevicePixelRatio(dpr);pix.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen=QPen(button.palette().color(QPalette.ColorRole.ButtonText),1.6);pen.setCapStyle(Qt.PenCapStyle.RoundCap);pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen);painter.translate(8,8);painter.rotate(float(angle))
    painter.drawLine(-2,-4,2,0);painter.drawLine(2,0,-2,4);painter.end()
    button.setIcon(QIcon(pix));button.setIconSize(QSize(16,16))

def font(role='body',weight=QFont.Weight.Normal,letter_spacing=0):
    f=QFont();f.setFamilies(TOKENS['fontFallbacks']);f.setPixelSize(TOKENS['font'].get(role,14));f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    return f

def palette(dark):
    p=TOKENS['dark' if dark else 'light']
    return dict(surface=p['canvas'],surface_low=p['panel'],surface_lowest=p['canvas'],surface_high=p['selected'],
        text=p['text'],muted=p['muted'],outline_variant=p['line'],primary=p['primary'],primary_container=p['primary'],
        focus_accent=p['focus'],success='#4ade80' if dark else '#15803d',danger='#f87171' if dark else '#b91c1c',warning='#fbbf24' if dark else '#a16207')

def harmonize(css):
    # Legacy widgets embed point sizes locally. Normalize the complete stylesheet
    # at its boundary so a child cannot silently return to a second type scale.
    sizes={9:13,10:14,10.5:14,11:16,15:22}
    css=re.sub(r'font-size:\s*([\d.]+)pt',lambda m:'font-size: '+str(sizes.get(float(m[1]),round(float(m[1])*4/3)))+'px',css)
    return re.sub(r'(border(?:-(?:top|bottom)-(?:left|right))?-radius:\s*)([\d.]+)px',lambda m:m[1]+str(TOKENS['layout']['radius'] if float(m[2])>=5 else m[2])+'px',css)

def stylesheet(dark):
    p=TOKENS['dark' if dark else 'light']
    return f'''
    QWidget {{ font-family: "Segoe UI", "Microsoft YaHei"; font-size: 14px; color: {p['text']}; }}
    QLabel#hero_title {{ font-size: 20px; font-weight: 600; padding: 0; }}
    QLabel#hero_subtitle {{ font-size: 14px; font-weight: 400; color: {p['muted']}; padding: 0; }}
    QLabel#stitch_label, QLabel#stitch_field_label {{ font-size: 13px; font-weight: 500; color: {p['muted']}; }}
    QLabel#stitch_settings_title, QLabel#stitch_subsection_title, QLabel#section_title {{ font-size: 16px; font-weight: 600; }}
    QFrame#topbar {{ background: {p['panel']}; }}
    QScrollArea#page_scroll, QWidget#page_root, QWidget#page_viewport, QWidget#page_canvas {{ background: {p['canvas']}; }}
    QFrame#card, QFrame#card_group, QFrame#card_soft, QFrame#stitch_file_card, QFrame#stitch_settings, QFrame#stitch_form_card {{ background: {p['canvas']}; border: 1px solid {p['line']}; border-radius: 8px; }}
    QFrame#stitch_pinned_bar {{ background: {p['canvas']}; border-top: 1px solid {p['line']}; }}
    QPushButton#secondary, QPushButton#primary, QPushButton#danger {{ min-height: 38px; max-height: 38px; padding: 0 12px; border: 1px solid {p['line']}; border-radius: 8px; font-size: 14px; font-weight: 500; }}
    QPushButton#secondary {{ background: {p['panel']}; color: {p['text']}; }}
    QPushButton#secondary:hover, QPushButton#secondary:pressed {{ background: {p['hover']}; border: 1px solid {p['line']}; }}
    QPushButton#primary, QPushButton#primary:hover, QPushButton#primary:pressed {{ background: {p['primary']}; color: {p['onPrimary']}; border-color: {p['primary']}; font-weight: 600; }}
    QPushButton#primary:disabled, QPushButton#secondary:disabled {{ background: {p['panel']}; color: {p['muted']}; border-color: {p['line']}; }}
    QPushButton#section_toggle {{ min-height: 30px; max-height: 30px; padding: 0; font-size: 14px; font-weight: 500; }}
    QLineEdit, QComboBox, QComboBox#stitch_combo, QSpinBox, QDoubleSpinBox {{ min-height: 38px; max-height: 38px; padding: 0 10px; background: {p['canvas']}; border: 1px solid {p['line']}; border-radius: 8px; font-size: 14px; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPushButton#primary:focus, QPushButton#secondary:focus {{ border: 1px solid {p['focus']}; }}
    QTextEdit, QPlainTextEdit, QTableWidget {{ font-size: 14px; background: {p['canvas']}; }}
    QFrame#task_status_panel QLabel, QLabel#status_hint {{ font-size: 12px; }}
    QTabBar#plan_modes::tab {{ background: transparent; color: {p['muted']}; font-size: 14px; font-weight: 500; padding: 8px 16px; border-bottom: 2px solid transparent; }}
    QTabBar#plan_modes::tab:selected {{ background: {p['panel']}; color: {p['text']}; border-bottom: 2px solid {p['text']}; }}
    QScrollArea#page_scroll QScrollBar:vertical {{ width: 6px; margin: 0; }}
    QLabel#nv_runtime_status {{ font-size: 12px; color: {p['muted']}; padding: 0 12px; background: {p['panel']}; }}
    '''

def theme_scrolls(page,dark):
    """Own the viewport and scrollbar containers, including local dashboard QSS."""
    p=TOKENS['dark' if dark else 'light']
    page_palette=page.palette()
    for role in (QPalette.ColorRole.Window,QPalette.ColorRole.Base):page_palette.setColor(role,QColor(p['canvas']))
    page.setPalette(page_palette);page.setAutoFillBackground(True)
    page.layout().setSpacing(0)
    for scroll in page.findChildren(QScrollArea):
        pal=scroll.palette()
        for role in (QPalette.ColorRole.Window,QPalette.ColorRole.Base):pal.setColor(role,QColor(p['canvas']))
        scroll.setPalette(pal);scroll.setAutoFillBackground(True)
        scroll.viewport().setPalette(pal);scroll.viewport().setAutoFillBackground(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f'''
            QWidget {{ font-family: "Segoe UI", "Microsoft YaHei"; }}
            QScrollArea {{ background: {p['canvas']}; border: 0; }}
            QScrollArea::corner {{ background: {p['canvas']}; border: 0; }}
            QScrollBar:vertical {{ width: 6px; margin: 0; background: {p['canvas']}; border: 0; }}
            QScrollBar:horizontal {{ height: 6px; margin: 0; background: {p['canvas']}; border: 0; }}
            QScrollBar::handle {{ background: {p['line']}; border-radius: 3px; min-width: 24px; min-height: 24px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: {p['canvas']}; border: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: {p['canvas']}; border: 0; }}
        ''')

def normalize_page(page,index):
    """Install one page grid without changing fields, signals or business order."""
    grid=TOKENS['layout'];inset=grid['pageInset']
    scroll=page.findChild(QScrollArea,'page_scroll')
    if not scroll:return
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    scroll.viewport().setObjectName('page_viewport')
    canvas=page.findChild(QWidget,'page_canvas')
    if index==0:
        root=canvas.layout();root.setContentsMargins(inset,grid['pageTop'],inset,24);root.setSpacing(grid['sectionGap'])
        # Dashboard actions occupy the same bottom action zone as all other pages.
        page._actions_pinned=True
        page.header_layout.removeWidget(page.action_container)
        pin=QFrame();pin.setObjectName('stitch_pinned_bar');lay=QVBoxLayout(pin)
        lay.addStretch(1)
        lay.addWidget(page.action_container);page.layout().addWidget(pin)
        page.action_container.layout().setContentsMargins(0,0,0,0)
    else:
        root=page.findChild(QWidget,'page_root').layout();root.setContentsMargins(inset,grid['pageTop'],inset,24)
        canvas.setMaximumWidth(16777215);canvas.layout().setContentsMargins(0,0,0,0);canvas.layout().setSpacing(grid['sectionGap'])
        # Panels retain their natural height as a drawer grows. The outer scroll
        # area absorbs overflow instead of compressing and redistributing cards.
        canvas.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
        canvas.layout().setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        for i in range(canvas.layout().count()):
            widget=canvas.layout().itemAt(i).widget()
            if widget is not None:widget.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
    title=page.findChild(QLabel,'hero_title')
    subtitle=page.findChild(QLabel,'hero_subtitle')
    descriptions=[
        '汇总活动数据，查看活动分布、院校覆盖、报销情况和专家信息。',
        '关联活动申请与报销记录，生成可用于看板和统计的数据表。',
        '按院校、活动类型和专业汇总数据，生成 Excel 统计报表。',
        '根据院校活动表生成 Word 简报；也可先将活动总表按院校拆分。',
        '按规则对发票分组，生成分组封面和明细表。',
        '填写活动信息生成方案，也可根据发票整理结果批量生成 Word 方案。',
        '启用后，自动处理指定文件夹中新加入的文件并提交打印。',
    ]
    page.setAccessibleName(title.text());page.setAccessibleDescription(descriptions[index])
    heading=title.parentWidget();heading.hide()
    if index==0:
        root.removeItem(page.header_layout)
    else:
        canvas.layout().removeWidget(heading)
        if canvas.layout().count() and canvas.layout().itemAt(0).spacerItem():canvas.layout().takeAt(0)
    pin=page.findChild(QFrame,'stitch_pinned_bar')
    if pin:
        pin.setFixedHeight(grid['footerHeight']);layout=pin.layout();layout.setContentsMargins(inset,12,inset+6,16);layout.setSpacing(grid['fieldGap'])
        for child in pin.findChildren(QWidget):
            if child.layout() and any(isinstance(child.layout().itemAt(i).widget(),QPushButton) for i in range(child.layout().count())):
                child.layout().setContentsMargins(0,0,0,0);child.layout().setSpacing(12)
        # Keep all action buttons at intrinsic width on the right; action bars no
        # longer stretch a label across half of the screen.
        def actions(layout):
            for i in range(layout.count()):
                item=layout.itemAt(i)
                if item.layout():actions(item.layout())
                elif item.widget() and item.widget().layout():actions(item.widget().layout())
            if isinstance(layout,QHBoxLayout) and any(isinstance(layout.itemAt(i).widget(),QPushButton) for i in range(layout.count())):
                for i in range(layout.count()):layout.setStretch(i,0)
                layout.insertStretch(0,1);layout.setSpacing(12)
        actions(layout)
        for button in pin.findChildren(QPushButton):
            if button.objectName()=='primary':
                button.setFixedWidth(180);button.setToolTip(button.text());button.setProperty('nv_process_action',True)
                if button is getattr(page,'refresh_button',None):button.setProperty('nv_dashboard_action',True)
                button.setAccessibleName(button.text());button.setIcon(QIcon())
    for button in page.findChildren(QPushButton):
        if button.objectName() in ('primary','secondary','danger'):
            button.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
            button.setFixedHeight(grid['controlHeight'])
            if getattr(button,'_stitch_icon_name',None):button.setIconSize(QSize(16,16))
            if not button.accessibleName():button.setAccessibleName(button.text())
    for field in page.findChildren(QLineEdit):field.setFixedHeight(grid['controlHeight'])
    for frame in page.findChildren(QFrame):
        if frame.objectName() in ('stitch_settings','stitch_file_card','stitch_form_card') and frame.layout():
            frame.layout().setContentsMargins(20,16,20,16);frame.layout().setSpacing(grid['fieldGap'])
    # Logs stay available, but empty technical output no longer dominates the page.
    for log in page.findChildren(QTextEdit,'stitch_run_log'):
        container=log.parentWidget();layout=container.layout()
        if not layout:continue
        label=next((x for x in container.findChildren(QLabel) if x.text()=='处理详情'),None)
        if label:layout.removeWidget(label);label.hide()
        toggle=QPushButton('处理详情');toggle.setObjectName('section_toggle');toggle.setCheckable(True)
        toggle.setAccessibleName('展开处理详情');toggle.setToolTip('展开查看完整处理记录')
        def change(opened,log=log,toggle=toggle):
            log.setVisible(opened);fold_indicator(toggle,90 if opened else 0)
            toggle.setAccessibleName('收起处理详情' if opened else '展开处理详情')
        toggle.toggled.connect(change);layout.insertWidget(0,toggle);log.hide();fold_indicator(toggle,0)
