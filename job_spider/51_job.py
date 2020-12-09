import base64
import re
import time
import cv2
import pytesseract
from io import BytesIO
import pymongo
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as Ec
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from job_spider.settings import *
from PIL import Image


class JobSpider:
    """1.破解滑块验证登录(后出现图片验证)
       2.输入搜索关键词：python
       3.xpath匹配，爬取岗位所需数据
       4.清洗数据，存入mongodb
    """

    def __init__(self):
        self.url = LOGIN_URL
        options = webdriver.ChromeOptions()
        # 此步骤很重要，设置为开发者模式，防止被各大网站识别出来使用了Selenium
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        self.browser = webdriver.Chrome(executable_path=DRIVER_PATH, options=options)
        self.browser.maximize_window()
        # 设置等待超时
        self.wait = WebDriverWait(self.browser, 10)
        # 访问网站
        self.browser.get(self.url)

    def get_tracks(self, distance):
        """拿到移动轨迹，模仿人的滑动行为，先匀加速后匀减速,匀变速运动基本公式：①v=v0+at,②s=v0t+½at²,③v²-v0²=2as
        :param distance: 需要移动的距离
        :return: 存放每0.3秒移动的距离
        """
        # 移动轨迹
        track = []
        # 当前位移
        current = 0
        # 减速阈值
        mid = distance * 4 / 5
        # 计算间隔
        t = 0.2
        # 初速度
        v = 0
        while current < distance:
            if current < mid:
                # 加速度为正2
                a = 2
            else:
                # 加速度为负3
                a = -3
            # 初速度v0
            v0 = v
            # 当前速度v = v0 + at
            v = v0 + a * t
            # 移动距离x = v0t + 1/2 * a * t^2
            move = v0 * t + 1 / 2 * a * t * t
            # 当前位移
            current += move
            # 加入轨迹
            track.append(round(move))
        return track

    def get_image1(self):
        """从网页的网站截图中，截取验证码图片
        :return:
        """
        img = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="slide_bg_img"]')))
        localtion = img.location
        size = img.size

        top = localtion['y']
        bottom = localtion['y'] + size['height']
        left = localtion['x']
        right = localtion['x'] + size['width']

        self.browser.save_screenshot('snap1.png')
        page_snap_obj = Image.open('snap1.png')
        crop_imag_obj = page_snap_obj.crop((left, top, right, bottom))
        return crop_imag_obj

    def get_image2(self):
        """从网页的网站截图中，截取缺口图片
        :return: 缺口图片
        """
        img = self.browser.find_element_by_xpath('//*[@id="slide_img"]/img').get_attribute('src')
        image_data = img.split(',')[1]
        binary_image_data = base64.b64decode(image_data, '-_')
        file_like = BytesIO(binary_image_data)
        image = Image.open(file_like)
        return image

    def process_slide_verification(self):
        """破解滑块验证"""
        # 步骤一：先点击按钮，弹出没有缺口的图片
        time.sleep(2)
        button = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="slide_btn_wrapper"]/span')))
        ActionChains(self.browser).move_to_element(button).perform()

        # 步骤二：拿到没有缺口的图片
        image1 = self.get_image1()

        # 步骤三：点击拖动按钮，弹出有缺口的图片
        button = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="slide_bg_img"]')))
        button.click()

        # 步骤四：拿到缺口图片
        image2 = self.get_image2()
        image2.save("./snap2.png")

        # 步骤五：二值化图片,进行对比，输出匹配的坐标系
        target_rgb = cv2.imread("./snap2.png")
        target_gray = cv2.cvtColor(target_rgb, cv2.COLOR_BGR2GRAY)
        template_rgb = cv2.imread("./snap1.png", 0)
        res = cv2.matchTemplate(target_gray, template_rgb, cv2.TM_CCOEFF_NORMED)
        value = cv2.minMaxLoc(res)
        print(value)
        distance = value[3][1] - 147.32
        print("需要位移的距离为：" + str(distance))
        # 步骤六：模拟人的行为习惯（先匀加速拖动后匀减速拖动），把需要拖动的总距离分成一段一段小的轨迹
        tracks = self.get_tracks(distance)
        # 步骤七：按照轨迹拖动，完全验证
        button = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="slide_btn"]')))
        ActionChains(self.browser).click_and_hold(button).perform()
        for track in tracks:
            ActionChains(self.browser).move_by_offset(xoffset=track, yoffset=0).perform()
        else:
            ActionChains(self.browser).move_by_offset(xoffset=3, yoffset=0).perform()  # 先移过一点
            ActionChains(self.browser).move_by_offset(xoffset=-3, yoffset=0).perform()  # 再退回来，是不是更像人了
        time.sleep(0.5)  # 0.5秒后释放鼠标
        ActionChains(self.browser).release().perform()

    def get_pictures(self):
        """获取图片验证码
        :return:
        """
        self.browser.save_screenshot('pictures.png')  # 全屏截图
        page_snap_obj = Image.open('pictures.png')
        img = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="verifyPic_img"]')))
        time.sleep(1)
        location = img.location
        size = img.size  # 获取验证码的大小参数
        left = location['x']
        top = location['y']
        right = left + size['width']
        bottom = top + size['height']
        image_obj = page_snap_obj.crop((left, top, right, bottom))  # 按照验证码的长宽，切割验证码
        image_obj.show()  # 打开切割后的完整验证码
        return image_obj

    def processing_image(self):
        """处理图片灰度
        :return:
        """
        image_obj = self.get_pictures()  # 获取验证码
        img = image_obj.convert("L")  # 转灰度
        pix_data = img.load()
        w, h = img.size
        threshold = 160
        # 遍历所有像素，大于阈值的为黑色
        for y in range(h):
            for x in range(w):
                if pix_data[x, y] < threshold:
                    pix_data[x, y] = 0
                else:
                    pix_data[x, y] = 255
        return img

    def delete_spot(self):
        """删除干扰的噪点
        :return:
        """
        images = self.processing_image()
        data = images.getdata()
        w, h = images.size
        black_point = 0
        for x in range(1, w - 1):
            for y in range(1, h - 1):
                mid_pixel = data[w * y + x]  # 中央像素点像素值
                if mid_pixel < 50:  # 找出上下左右四个方向像素点像素值
                    top_pixel = data[w * (y - 1) + x]
                    left_pixel = data[w * y + (x - 1)]
                    down_pixel = data[w * (y + 1) + x]
                    right_pixel = data[w * y + (x + 1)]
                    # 判断上下左右的黑色像素点总个数
                    if top_pixel < 10:
                        black_point += 1
                    if left_pixel < 10:
                        black_point += 1
                    if down_pixel < 10:
                        black_point += 1
                    if right_pixel < 10:
                        black_point += 1
                    if black_point < 1:
                        images.putpixel((x, y), 255)
                    black_point = 0
        return images

    def picture_verification_login(self):
        """图片验证登录
        :return:
        """
        image = self.delete_spot()
        pytesseract.pytesseract.tesseract_cmd = r"E:\OCR\tesseract.exe"  # 设置pyteseract路径
        result = pytesseract.image_to_string(image)  # 图片转文字
        result_code = re.sub(u"([^\u4e00-\u9fa5\u0030-\u0039\u0041-\u005a\u0061-\u007a])", "", result)  # 去除识别出来的特殊字符
        print(result_code)  # 打印识别的验证码
        code_input = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="verifycode"]')))
        code_input.send_keys()

    def login(self):
        """登录
        :return:
        """
        try:
            login_click = self.wait.until(
                Ec.presence_of_element_located((By.XPATH, '/html/body/div[1]/div[1]/div/div[3]/p/a[1]')))
            login_click.click()
            account_input = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="loginname"]')))
            account_input.send_keys(USER_NAME)
            password_input = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="password"]')))
            password_input.send_keys(PASSWORD)
            # 破解滑块验证
            # self.process_slide_verification()
            # 破解图片验证
            self.picture_verification_login()
            submit = self.wait.until(Ec.presence_of_element_located((By.XPATH, '//*[@id="login_btn"]')))
            submit.click()
        except TimeoutException as e:
            self.browser.close()


if __name__ == '__main__':
    job = JobSpider()
    job.login()
